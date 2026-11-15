"""调度引擎：持久队列 + 常驻并发 worker + 优雅停机 + 断点续爬 + 实时指标。"""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from pathlib import Path

from .adaptive import AdaptiveConcurrency
from .config import Config
from .extractor import Extractor
from .fetcher import Fetcher
from .frontier import Frontier
from .metrics import Metrics
from .models import Item, Request
from .pipeline import MiddlewareChain, PipelineManager
from .ratelimit import DomainLimiter
from .robots import RobotsPolicy
from .utils import host_of, human_bytes, normalize_url


class Crawler:
    """通用爬虫引擎。典型用法：

        from opencrawler import Config, Crawler
        asyncio.run(Crawler(Config.from_dict({"seeds": ["https://example.com"]})).run())
    """

    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.log = logging.getLogger("opencrawler.engine")
        self.metrics = Metrics()
        self.frontier: Frontier | None = None
        self._tasks: dict[asyncio.Task, Request] = {}
        self._inflight: dict[str, int] = {}
        self._pages_done = 0
        self._stop: asyncio.Event | None = None
        self._stop_reason = ""
        self._started = 0.0
        self._running = False
        self._pending_stop = False
        self.adaptive = (
            AdaptiveConcurrency(
                config.concurrency,
                target_latency_ms=config.adaptive_target_latency_ms,
            )
            if config.adaptive_concurrency
            else None
        )

    # ---------------- 主循环 ----------------
    async def run(self) -> dict:
        if self.cfg.dry_run:
            return self._dry_run()
        for warning in self.cfg.warnings:
            self.log.warning("配置提醒: %s", warning)
        Path(self.cfg.output_dir).mkdir(parents=True, exist_ok=True)
        self._started = time.monotonic()
        self._stop = asyncio.Event()
        self._running = True
        if self._pending_stop:
            self._stop.set()
            self._pending_stop = False
        self.metrics = Metrics()

        self.frontier = Frontier(self.cfg.state_file, resume=True)
        self._seed()

        limiter = DomainLimiter(
            default_delay_ms=self.cfg.default_delay_ms,
            per_domain_delay_ms=self.cfg.per_domain_delay_ms,
            per_domain_rps=self.cfg.per_domain_rps,
            per_domain_concurrency=self.cfg.per_domain_concurrency,
        )
        self.pipeline = PipelineManager(self.cfg, self.frontier, self.log)
        self.middlewares = MiddlewareChain(self.cfg.middlewares, self.log)
        self.extractor = Extractor(self.cfg, self.log)

        async with Fetcher(self.cfg, self.frontier, self.log) as fetcher:
            self.fetcher = fetcher
            self.limiter = limiter
            fetcher._penalty_hook = lambda url, seconds: limiter.penalize(host_of(url), seconds)
            self.robots = RobotsPolicy(
                fetcher.get_text,
                enabled=self.cfg.respect_robots,
                user_agent=self.cfg.user_agent,
                ttl=self.cfg.robots_cache_ttl,
                on_error=self.cfg.robots_on_error,
                obey_crawl_delay=self.cfg.obey_crawl_delay,
                logger=self.log,
            )
            await self._discover_sitemaps()
            self._install_signal_handlers()
            self._metrics_task = asyncio.create_task(self._metrics_loop())

            idle_since = 0.0
            try:
                while not self._stop.is_set():
                    if self._budget_reached():
                        break
                    limit = self.adaptive.limit if self.adaptive else self.cfg.concurrency
                    available = max(0, limit - len(self._tasks))
                    if available > 0:
                        batch = self.frontier.pop_batch(
                            available,
                            per_domain_limit=self.cfg.per_domain_concurrency,
                            inflight=self._inflight,
                        )
                        for request in batch:
                            task = asyncio.create_task(self._process(request))
                            self._tasks[task] = request
                    if self._tasks:
                        done, _ = await asyncio.wait(
                            self._tasks.keys(), timeout=0.25, return_when=asyncio.FIRST_COMPLETED
                        )
                        for task in done:
                            self._reap(task)
                    else:
                        queued = self.frontier.counts()["queued"]
                        if queued == 0:
                            idle_since = idle_since or time.monotonic()
                            if time.monotonic() - idle_since > 1.0:
                                self._stop_reason = "队列已清空"
                                break
                        else:
                            idle_since = 0.0
                        await asyncio.sleep(0.1)
            except KeyboardInterrupt:
                self._stop_reason = "用户中断 (Ctrl+C)"
            finally:
                await self._shutdown_gracefully()

        await self.pipeline.close()
        counts = self.frontier.counts()
        self.log.info("完成: %s | %s", self._stop_reason or "达到停止条件", self.metrics.render(counts=counts))
        summary = self.metrics.snapshot(counts=counts)
        summary["stop_reason"] = self._stop_reason or "达到停止条件"
        summary["state_file"] = self.cfg.state_file
        summary["output_dir"] = self.cfg.output_dir
        self.frontier.close()
        self._running = False
        return summary

    # ---------------- 桌面 / 外部控制 ----------------
    def request_stop(self, reason: str = "外部请求停止") -> None:
        """线程安全地请求优雅停机；未开始运行时会在启动后立即生效。"""
        self._stop_reason = reason
        if self._stop and not self._stop.is_set():
            self._stop.set()
        else:
            self._pending_stop = True

    def snapshot(self) -> dict:
        """返回当前运行快照，供桌面 UI 轮询。"""
        counts = self.frontier.counts() if self.frontier else {}
        snap = self.metrics.snapshot(counts=counts, inflight=len(self._tasks))
        snap.update({
            "running": self._running,
            "stop_reason": self._stop_reason,
            "adaptive": self.adaptive.snapshot() if self.adaptive else {"enabled": False},
        })
        return snap

    def _dry_run(self) -> dict:
        self.log.info("DRY-RUN（不会发出任何网络请求）")
        for seed in self.cfg.seeds:
            print(f"  seed: {normalize_url(seed)}")
        print(
            f"  并发 {self.cfg.concurrency} / 每域 {self.cfg.per_domain_concurrency} | "
            f"深度 {self.cfg.max_depth} | 上限 {self.cfg.max_pages} 页 | "
            f"限速 {self.cfg.default_delay_ms}ms | robots={self.cfg.respect_robots} | "
            f"抽取={self.cfg.extract_mode} | 存储={self.cfg.storage}"
        )
        return {"dry_run": True, "seeds": self.cfg.seeds, "config": self.cfg.to_dict()}

    def _seed(self) -> None:
        assert self.frontier is not None
        seeds = []
        for url in self.cfg.seeds:
            normalized = normalize_url(url)
            if normalized:
                ok, reason = Extractor(self.cfg, self.log).should_follow(normalized, 0)
                if not ok:
                    self.log.warning("跳过种子 %s: %s", normalized, reason)
                    continue
                seeds.append(Request(normalized, depth=0, priority=100, kind="page"))
        added = self.frontier.add_many(seeds)
        self.log.info("种子 %d 个（新增 %d），队列 %s", len(seeds), added, self.frontier.counts())

    async def _discover_sitemaps(self) -> None:
        if not (self.cfg.follow_sitemaps and self.cfg.respect_robots):
            return
        assert self.frontier is not None
        requests = []
        for seed in self.cfg.seeds[:20]:
            for url in await self.robots.sitemaps(seed):
                normalized = normalize_url(url)
                if normalized:
                    requests.append(Request(normalized, depth=0, priority=50, kind="sitemap"))
        if requests:
            self.frontier.add_many(requests)
            self.log.info("从 robots.txt 发现 %d 个 Sitemap", len(requests))

    # ---------------- 单个请求 ----------------
    async def _process(self, request: Request) -> None:
        host = host_of(request.url)
        self._inflight[host] = self._inflight.get(host, 0) + 1
        try:
            if self._stop and self._stop.is_set():
                return  # 保持 in-flight 状态，关闭时自动重新入队
            if self._budget_reached():
                return
            if not await self.middlewares.before(request):
                self.frontier.mark_done(request.url, note="中间件丢弃")
                return

            allowed, reason = await self.robots.allowed(request.url)
            if not allowed:
                self.frontier.mark_done(request.url, note=f"robots: {reason}")
                self.metrics.skipped += 1
                self.log.debug("跳过 %s: %s", request.url, reason)
                return

            delay_ms = (await self.robots.crawl_delay(request.url)) * 1000.0
            async with self.limiter.slot(host, delay_ms):
                outcome = await self.fetcher.fetch(request)

            if self.adaptive:
                latency = (outcome.response.elapsed_ms if outcome.response
                           else self.cfg.request_timeout * 1000.0)
                self.adaptive.record(latency, not outcome.error)

            if outcome.error:
                self.metrics.failed += 1
                self.metrics.errors[outcome.error.split(":")[0]] += 1
                if outcome.error.startswith("HTTP 4"):
                    self.frontier.mark_done(request.url, note=outcome.error)
                else:
                    if self.frontier.mark_failed(request, self.cfg.retries + 1, outcome.error):
                        self.metrics.retries += 1
                self.log.debug("失败 %s: %s", request.url, outcome.error)
                return
            if outcome.not_modified:
                self.frontier.mark_done(request.url, note="304 Not Modified")
                self.metrics.not_modified += 1
                return

            response = outcome.response
            if response is None:
                return
            self.metrics.record_response(request.url, response.status, response.size, host)
            if outcome.skipped:
                self.frontier.mark_done(request.url, note=outcome.skipped)
                self.metrics.skipped += 1
                return
            if not await self.middlewares.after(request, response):
                self.frontier.mark_done(request.url, note="中间件丢弃响应")
                return

            extracted = self.extractor.extract(response)
            if extracted.skip:
                self.frontier.mark_done(request.url, extracted.content_hash, extracted.reason)
                self.metrics.skipped += 1
                return

            item = Item(
                data=extracted.item, url=request.url,
                kind=request.kind, content_hash=extracted.content_hash,
            )
            ok, why = await self.pipeline.process(item)
            if ok:
                self.metrics.items += 1
            else:
                self.metrics.duplicates += 1
                self.log.debug("跳过条目 %s: %s", request.url, why)

            if extracted.links:
                self.frontier.add_many(extracted.links)
                self.metrics.links += len(extracted.links)
            self.frontier.mark_done(request.url, extracted.content_hash, "ok")
            self._pages_done += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 单任务异常不得拖垮引擎
            self.log.exception("处理 %s 时异常: %s", request.url, exc)
            self.metrics.failed += 1
            try:
                self.frontier.mark_failed(request, self.cfg.retries + 1, type(exc).__name__)
            except Exception:  # noqa: BLE001
                pass
        finally:
            self._inflight[host] = max(0, self._inflight.get(host, 1) - 1)

    def _reap(self, task: asyncio.Task) -> None:
        self._tasks.pop(task, None)
        if not task.done():
            return
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            self.log.debug("任务异常: %s", exc)

    # ---------------- 停机与指标 ----------------
    def _budget_reached(self) -> bool:
        if self._pages_done >= self.cfg.max_pages:
            self._stop_reason = f"达到页数上限 {self.cfg.max_pages}"
            return True
        if self.metrics.bytes_downloaded >= self.cfg.max_bytes:
            self._stop_reason = f"达到流量上限 {human_bytes(self.cfg.max_bytes)}"
            return True
        if self.cfg.time_budget_seconds and self.metrics.elapsed() >= self.cfg.time_budget_seconds:
            self._stop_reason = f"达到时间预算 {self.cfg.time_budget_seconds}s"
            return True
        return False

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()

        def stop() -> None:
            if self._stop and not self._stop.is_set():
                self.log.warning("收到停止信号，正在保存进度…")
                self._stop_reason = "收到停止信号"
                self._stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop)
            except (NotImplementedError, RuntimeError, ValueError):
                pass  # Windows 事件循环可能不支持 SIGTERM

    async def _metrics_loop(self) -> None:
        assert self.frontier is not None
        try:
            while True:
                await asyncio.sleep(max(1.0, self.cfg.metrics_interval))
                counts = self.frontier.counts()
                self.log.info(self.metrics.render(counts=counts, inflight=len(self._tasks)))
                self.metrics.write(
                    Path(self.cfg.output_dir) / "metrics.jsonl",
                    counts=counts, inflight=len(self._tasks),
                )
        except asyncio.CancelledError:
            return

    async def _shutdown_gracefully(self) -> None:
        if self._stop:
            self._stop.set()
        if hasattr(self, "_metrics_task"):
            self._metrics_task.cancel()
        if self._tasks:
            self.log.info("等待 %d 个进行中的请求收尾…", len(self._tasks))
            done, pending = await asyncio.wait(
                self._tasks.keys(), timeout=min(self.cfg.request_timeout, 15.0)
            )
            for task in done:
                self._reap(task)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._tasks.clear()
        assert self.frontier is not None
        counts = self.frontier.counts()
        self.metrics.write(
            Path(self.cfg.output_dir) / "metrics.jsonl", counts=counts, inflight=0
        )
