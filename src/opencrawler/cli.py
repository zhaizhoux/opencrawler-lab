"""命令行入口：crawl / fetch / demo / selftest / validate / init / version。"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import __version__


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--config", help="JSON/YAML/TOML 配置文件")
    parser.add_argument("--seed", action="append", default=None, help="起始 URL（可重复）")
    parser.add_argument("--out", dest="output_dir", help="输出目录")
    parser.add_argument("--concurrency", type=int, help="全局并发数")
    parser.add_argument("--per-domain-concurrency", type=int, help="单域名并发数")
    parser.add_argument("--max-pages", type=int, help="最多抓取页面数")
    parser.add_argument("--max-depth", type=int, help="最大链接深度")
    parser.add_argument("--delay-ms", dest="default_delay_ms", type=int, help="每域最小请求间隔(毫秒)")
    parser.add_argument("--time-budget", dest="time_budget_seconds", type=int, help="运行时长上限(秒)")
    parser.add_argument("--mode", dest="extract_mode", choices=["auto", "rules", "both", "raw"], help="抽取模式")
    parser.add_argument("--storage", choices=["jsonl", "sqlite", "none"], help="存储后端")
    parser.add_argument("--proxy", help="HTTP 代理地址（仅用于自有网络环境）")
    parser.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING/ERROR")
    parser.add_argument("--dry-run", action="store_true", default=None, help="只打印计划，不发出请求")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opencrawler",
        description="OpenCrawlerLab —— 用于学习的通用、合规、异步高并发爬虫框架",
        epilog="请只抓取公开且允许抓取的页面，详见 ETHICS.md",
    )
    parser.add_argument("--version", action="version", version=f"OpenCrawlerLab {__version__}")
    sub = parser.add_subparsers(dest="command")

    crawl = sub.add_parser("crawl", help="运行一次（可断点续爬的）抓取任务")
    _add_common(crawl)

    fetch = sub.add_parser("fetch", help="只抓一个 URL 并打印抽取结果，用于调试规则")
    fetch.add_argument("url")
    fetch.add_argument("-c", "--config")
    fetch.add_argument("--log-level", default="WARNING")

    demo = sub.add_parser("demo", help="启动内置演示站点（无需公网）")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8765)

    desktop = sub.add_parser("desktop", help="启动桌面应用（本地服务 + 独立窗口）")
    desktop.add_argument("--host", default="127.0.0.1")
    desktop.add_argument("--port", type=int, default=8756)
    desktop.add_argument("--no-browser", action="store_true", help="只启动服务，不打开窗口")

    sub.add_parser("selftest", help="在内存中启动演示站点并完整自测一次抓取")
    sub.add_parser("version", help="打印版本号")

    validate = sub.add_parser("validate", help="校验配置文件")
    validate.add_argument("-c", "--config", required=True)

    init = sub.add_parser("init", help="生成一份带注释的示例配置")
    init.add_argument("-o", "--output", default="crawler.config.json")
    return parser


def _load_config(args: argparse.Namespace) -> Any:
    from .config import Config

    overrides = {
        key: getattr(args, key, None)
        for key in (
            "seeds", "output_dir", "concurrency", "per_domain_concurrency",
            "max_pages", "max_depth", "default_delay_ms", "time_budget_seconds",
            "extract_mode", "storage", "proxy", "log_level", "dry_run",
        )
    }
    # --seed 映射到 seeds；None 值会被 Config.from_dict 忽略
    overrides["seeds"] = getattr(args, "seed", None)
    overrides = {k: v for k, v in overrides.items() if v not in (None, [], False)}
    if getattr(args, "dry_run", False):
        overrides["dry_run"] = True
    config_path = getattr(args, "config", None)
    if config_path:
        return Config.from_file(config_path, **overrides)
    return Config.from_dict({"seeds": overrides.pop("seeds", [])}, **overrides)


async def _crawl(args: argparse.Namespace) -> int:
    from .engine import Crawler

    cfg = _load_config(args)
    configure_logging(cfg.log_level)
    if not cfg.seeds and not getattr(args, "config", None):
        print("错误：请提供 --seed 或 --config（示例：opencrawler crawl --seed https://example.com）", file=sys.stderr)
        return 2
    summary = await Crawler(cfg).run()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


async def _fetch_one(args: argparse.Namespace) -> int:
    from .config import Config
    from .extractor import Extractor
    from .fetcher import Fetcher
    from .frontier import Frontier
    from .models import Request
    from .robots import RobotsPolicy

    configure_logging(args.log_level)
    cfg = (Config.from_file(args.config) if args.config else Config.from_dict({"seeds": [args.url]}))
    with tempfile.TemporaryDirectory(prefix="opencrawler-fetch-") as tmp:
        cfg.output_dir = tmp
        cfg.state_file = str(Path(tmp) / "state.sqlite3")
        frontier = Frontier(cfg.state_file)
        async with Fetcher(cfg, frontier) as fetcher:
            robots = RobotsPolicy(
                fetcher.get_text, enabled=cfg.respect_robots, user_agent=cfg.user_agent,
                on_error=cfg.robots_on_error, obey_crawl_delay=cfg.obey_crawl_delay,
            )
            allowed, reason = await robots.allowed(args.url)
            if not allowed:
                print(json.dumps({"error": f"按 robots.txt 拒绝抓取: {reason}"}, ensure_ascii=False))
                return 3
            result = await fetcher.fetch(Request(args.url))
            if result.error:
                print(json.dumps({"error": result.error}, ensure_ascii=False))
                return 1
            if result.not_modified:
                print(json.dumps({"not_modified": True}, ensure_ascii=False))
                return 0
            if result.skipped:
                print(json.dumps({"skipped": result.skipped}, ensure_ascii=False))
                return 0
            assert result.response is not None
            extracted = Extractor(cfg).extract(result.response)
            payload = {
                "url": args.url,
                "status": result.response.status,
                "content_type": result.response.content_type,
                "elapsed_ms": result.response.elapsed_ms,
                "item": extracted.item,
                "links": [r.url for r in extracted.links][:50],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        frontier.close()
    return 0


async def _selftest() -> int:
    from aiohttp import web

    from .config import Config
    from .demo import create_app
    from .engine import Crawler

    configure_logging("WARNING")
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001 - 仅用于内部自测
    base = f"http://127.0.0.1:{port}"
    ok = False
    try:
        with tempfile.TemporaryDirectory(prefix="opencrawler-selftest-") as tmp:
            cfg = Config.from_dict(
                {
                    "seeds": [base + "/"],
                    "output_dir": tmp,
                    "concurrency": 8,
                    "per_domain_concurrency": 4,
                    "default_delay_ms": 0,
                    "per_domain_rps": 100,
                    "max_pages": 50,
                    "max_depth": 3,
                    "respect_robots": True,
                    "follow_sitemaps": True,
                    "log_level": "WARNING",
                    "metrics_interval": 1,
                    "retries": 1,
                }
            )
            summary = await Crawler(cfg).run()
            lines = (Path(tmp) / "items.jsonl").read_text(encoding="utf-8").splitlines()
            crawled = [json.loads(line)["url"] for line in lines]
            forbidden = [u for u in crawled if u.rstrip("/").endswith("/secret") or "/admin/" in u]
            external = [u for u in crawled if "example.org" in u]
            ok = len(crawled) >= 5 and not forbidden and not external
            print(json.dumps({
                "selftest": "PASS" if ok else "FAIL",
                "pages_collected": len(crawled),
                "robots_disallowed_crawled": forbidden,
                "external_crawled": external,
                "summary": {k: summary[k] for k in ("requests", "succeeded", "items", "duplicates", "stop_reason")},
            }, ensure_ascii=False, indent=2))
    finally:
        await runner.cleanup()
    return 0 if ok else 1


def _init_config(path: str) -> int:
    from .config import Config
    sample = Config.from_dict({"seeds": ["https://example.com/"]}).to_dict()
    sample["seeds"] = ["https://example.com/"]
    sample["rules"] = [
        {
            "name": "article",
            "url_pattern": "/article/",
            "fields": {
                "title": {"selector": "h1", "transform": "strip"},
                "date": {"selector": "time.published", "attr": "datetime"},
                "tags": {"selector": ".tag", "many": True, "limit": 10},
                "price": {"regex": r"¥\s*([0-9.]+)", "transform": "float"},
            },
        }
    ]
    Path(path).write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成示例配置: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "crawl"
    try:
        if command == "crawl":
            return asyncio.run(_crawl(args))
        if command == "fetch":
            return asyncio.run(_fetch_one(args))
        if command == "demo":
            from .demo import serve
            return asyncio.run(serve(args.host, args.port))
        if command == "desktop":
            from .server import launch
            configure_logging("INFO")
            return asyncio.run(launch(args.host, args.port, browser=not args.no_browser))
        if command == "selftest":
            return asyncio.run(_selftest())
        if command == "validate":
            from .config import Config
            configure_logging("INFO")
            cfg = Config.from_file(args.config)
            print(json.dumps({"valid": True, "config": cfg.to_dict(), "warnings": cfg.warnings},
                             ensure_ascii=False, indent=2))
            return 0
        if command == "init":
            return _init_config(args.output)
        if command == "version":
            print(f"OpenCrawlerLab {__version__}")
            return 0
    except KeyboardInterrupt:
        print("\n已中断；进度已保存，重新执行同一命令即可续爬。", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI 顶层统一报错
        print(f"错误: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
