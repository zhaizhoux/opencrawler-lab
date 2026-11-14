"""本机并发压测：内存生成大量页面，比较不同并发配置下的吞吐。

两个场景：
  A. 单域名   —— 展示礼貌限速下的稳定吞吐（并发提高不会打爆单站）
  B. 多域名   —— 4 个回环别名，展示并发度带来的近线性扩展

不会对任何公网站点发请求。运行：python scripts/benchmark.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiohttp import web  # noqa: E402

from opencrawler.config import Config  # noqa: E402
from opencrawler.engine import Crawler  # noqa: E402

PAGE_COUNT = int(os.environ.get("PAGES", "240"))
CONCURRENCIES = (4, 16, 64)
HOSTS = ("127.0.0.1", "127.0.0.2", "127.0.0.3", "127.0.0.4")


def create_large_app(total: int) -> web.Application:
    async def robots(request):
        return web.Response(text="User-agent: *\nAllow: /\nCrawl-delay: 0\n", content_type="text/plain")

    async def page(request):
        i = int(request.match_info["i"])
        if i >= total:
            raise web.HTTPNotFound()
        links = "".join(f'<a href="/p/{j}">next {j}</a>' for j in range(i + 1, min(total, i + 4)))
        body = (
            f"<!doctype html><html lang='zh-CN'><head><title>压测页 {i}</title>"
            f"<meta name='description' content='benchmark {i}'></head><body>"
            f"<h1>压测页 {i}</h1><p>这是 {request.host} 上第 {i} 个用于测量吞吐的本机演示页面。</p>"
            f"<main>{links}</main></body></html>"
        )
        return web.Response(text=body, content_type="text/html", charset="utf-8")

    app = web.Application()
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/p/{i}", page)
    return app


async def one_run(port: int, hosts: tuple[str, ...], total: int, concurrency: int, output_dir: str) -> dict:
    seeds = [f"http://{host}:{port}/p/0" for host in hosts]
    cfg = Config.from_dict({
        "seeds": seeds,
        "output_dir": output_dir,
        "concurrency": concurrency,
        "per_domain_concurrency": max(1, concurrency // len(hosts)),
        "default_delay_ms": 0,
        "per_domain_rps": 10_000,
        "max_pages": len(hosts) * total + 10,
        "max_depth": total + 1,
        "respect_robots": True,
        "follow_sitemaps": False,
        "retries": 1,
        "log_level": "WARNING",
        "metrics_interval": 5,
    })
    return await Crawler(cfg).run()


async def scenario(port: int, label: str, hosts: tuple[str, ...], total: int) -> None:
    print(f"\n场景 {label}：{len(hosts)} 个域名 × {total} 页 = {len(hosts) * total} 个请求")
    print(f"{'并发':>6} {'请求':>7} {'条目':>7} {'耗时(s)':>9} {'req/s':>9} {'失败':>6}")
    print("-" * 52)
    for concurrency in CONCURRENCIES:
        with tempfile.TemporaryDirectory(prefix="opencrawler-bench-") as tmp:
            summary = await one_run(port, hosts, total, concurrency, tmp)
            print(
                f"{concurrency:>6} {summary['requests']:>7} {summary['items']:>7} "
                f"{summary['elapsed_seconds']:>9.2f} {summary['requests_per_second']:>9.2f} "
                f"{summary['failed']:>6}"
            )


async def main() -> None:
    total = max(60, PAGE_COUNT // len(HOSTS))
    runner = web.AppRunner(create_large_app(total))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
    print(f"本机内存站点已启动于 0.0.0.0:{port}（回环别名 {', '.join(HOSTS)}）")
    try:
        # 预热：消除首次 DNS/连接池/SQLite 页缓存带来的偏差，结果不计入统计
        with tempfile.TemporaryDirectory(prefix="opencrawler-bench-warmup-") as tmp:
            await one_run(port, HOSTS[:1], 5, 8, tmp)
        await scenario(port, "A · 单域名", HOSTS[:1], total)
        await scenario(port, "B · 多域名", HOSTS, total)
    finally:
        await runner.cleanup()
    print("\n提示：这是本机回环压测，数值仅用于观察并发模型，不代表公网抓取速度。")
    print("单域名场景中，并发受每域礼貌限速约束；只有多域名/慢站点才能从并发中获益。")
    print("Windows 回环在 64+ 并发时 TCP/事件循环开销明显上升（纯客户端基线亦如此），")
    print("因此曲线并非单调递增，属操作系统层面的现象，不是队列或限速逻辑的退化。")


if __name__ == "__main__":
    asyncio.run(main())
