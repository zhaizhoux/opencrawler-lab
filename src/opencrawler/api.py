"""极简高层 API：把常用场景压缩成一行。

    from opencrawler import crawl
    report = crawl("https://example.com/", max_pages=20)

    from opencrawler import Session
    with Session(concurrency=64, output_dir="./out") as s:
        report = s.run(["https://a.example/", "https://b.example/"])

需要精细控制时，仍可直接使用 ``Config`` + ``Crawler``。
"""
from __future__ import annotations

import asyncio
from typing import Any, Iterable

from .config import Config
from .engine import Crawler

__all__ = ["Session", "crawl", "crawl_async", "plan"]


def _as_list(urls: str | Iterable[str]) -> list[str]:
    return [urls] if isinstance(urls, str) else list(urls)


class Session:
    """可复用的抓取会话，配置只写一次，可连续运行多批种子。"""

    def __init__(self, **options: Any) -> None:
        # 构造时即校验，错误尽早暴露
        Config.from_dict(dict(options))
        self.options = dict(options)
        self.last_config: Config | None = None
        self.last_crawler: Crawler | None = None
        self.reports: list[dict] = []

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def run(self, urls: str | Iterable[str], **overrides: Any) -> dict:
        """同步运行，返回指标摘要。"""
        return asyncio.run(self.run_async(urls, **overrides))

    async def run_async(self, urls: str | Iterable[str], **overrides: Any) -> dict:
        cfg = Config.from_dict({**self.options, **overrides, "seeds": _as_list(urls)})
        crawler = Crawler(cfg)
        self.last_config, self.last_crawler = cfg, crawler
        report = await crawler.run()
        self.reports.append(report)
        return report

    def plan(self, urls: str | Iterable[str], **overrides: Any) -> dict:
        """不发出任何网络请求，返回本次运行计划。"""
        cfg = Config.from_dict({**self.options, **overrides, "seeds": _as_list(urls),
                                "dry_run": True})
        return Crawler(cfg)._dry_run()


def crawl(urls: str | Iterable[str], **options: Any) -> dict:
    """一行抓取；等价于 ``Session(**options).run(urls)``。"""
    return Session(**options).run(urls)


async def crawl_async(urls: str | Iterable[str], **options: Any) -> dict:
    """在已有事件循环中抓取（供 async 应用调用）。"""
    return await Session(**options).run_async(urls)


def plan(urls: str | Iterable[str], **options: Any) -> dict:
    """只列计划，不联网。"""
    return Session(**options).plan(urls)
