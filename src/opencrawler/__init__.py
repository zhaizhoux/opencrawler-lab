"""OpenCrawlerLab —— 用于学习的通用、合规、高并发爬虫框架。

只抓公开页面；默认遵守 robots.txt、限速、去重、限深，不提供任何绕过
验证码、登录墙或反爬机制的能力。详见 ETHICS.md。

最简用法::

    from opencrawler import crawl
    report = crawl("https://example.com/", max_pages=20)
"""
from __future__ import annotations

from typing import Any

__version__ = "0.3.0"
__all__ = [
    "Crawler", "Config", "Session", "crawl", "crawl_async", "plan",
    "Request", "Response", "Item", "__version__",
]


def __getattr__(name: str) -> Any:
    # 延迟导入：即使未安装可选依赖，也能查看版本号与读取文档
    if name == "Config":
        from .config import Config
        return Config
    if name == "Crawler":
        from .engine import Crawler
        return Crawler
    if name in {"Session", "crawl", "crawl_async", "plan"}:
        from . import api
        return getattr(api, name)
    if name in {"Request", "Response", "Item"}:
        from . import models
        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
