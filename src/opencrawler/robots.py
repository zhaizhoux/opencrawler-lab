"""robots.txt 合规策略：按主机缓存、解析 Allow/Disallow、Crawl-delay 与 Sitemap。"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Awaitable, Callable

FetchText = Callable[[str], Awaitable[tuple[int, str]]]

_CRAWL_DELAY = re.compile(r"^\s*crawl-delay\s*:\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_SITEMAP = re.compile(r"^\s*sitemap\s*:\s*(\S+)", re.I)
_UA_LINE = re.compile(r"^\s*user-agent\s*:\s*(.+?)\s*$", re.I)


@dataclass(slots=True)
class _RobotsData:
    status: int
    parser: urllib.robotparser.RobotFileParser
    delay: float | None = None
    sitemaps: list[str] = field(default_factory=list)
    fetched_at: float = 0.0


def parse_robots(text: str, user_agent: str) -> tuple[urllib.robotparser.RobotFileParser, float | None, list[str]]:
    """解析 robots.txt，返回 (规则解析器, 适用于本 UA 的 Crawl-delay, Sitemap 列表)。"""
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    sitemaps = [m.group(1) for line in text.splitlines() if (m := _SITEMAP.match(line))]

    delay: float | None = None
    current_agents: list[str] = []
    last_was_ua = False
    ua_lower = user_agent.lower()
    for line in text.splitlines():
        cleaned = line.split("#", 1)[0].strip()
        if not cleaned:
            continue
        if m := _UA_LINE.match(cleaned):
            if not last_was_ua:
                current_agents = []  # 新的 User-agent 组开始
            current_agents.append(m.group(1).strip().lower())
            last_was_ua = True
            continue
        last_was_ua = False
        if m := _CRAWL_DELAY.match(cleaned):
            if not current_agents:
                continue
            wildcard = "*" in current_agents
            matched = any(a in ua_lower or a == "*" for a in current_agents)
            if matched:
                value = float(m.group(1))
                # 取最保守（最大）的适用值
                delay = max(delay or 0.0, value)
            elif wildcard:
                # 组不匹配但存在通配符时仍保留一个兜底值
                delay = max(delay or 0.0, float(m.group(1)))
    return parser, delay, sitemaps


class RobotsPolicy:
    """并发安全地按主机懒加载 robots.txt。"""

    def __init__(
        self,
        fetch_text: FetchText,
        *,
        enabled: bool = True,
        user_agent: str = "*",
        ttl: int = 3600,
        on_error: str = "deny",
        obey_crawl_delay: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._fetch_text = fetch_text
        self.enabled = enabled
        self.user_agent = user_agent
        self.ttl = ttl
        self.on_error = on_error
        self.obey_crawl_delay = obey_crawl_delay
        self.log = logger or logging.getLogger("opencrawler.robots")
        self._cache: dict[str, _RobotsData] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _origin(url: str) -> str:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        # 必须保留端口，否则本地/非标准端口站点的 robots.txt 会取错
        return f"{parts.scheme}://{parts.netloc}"

    async def _get(self, url: str) -> _RobotsData:
        origin = self._origin(url)
        cached = self._cache.get(origin)
        if cached and time.monotonic() - cached.fetched_at < self.ttl:
            return cached
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            cached = self._cache.get(origin)
            if cached and time.monotonic() - cached.fetched_at < self.ttl:
                return cached
            robots_url = origin + "/robots.txt"
            status, text = 0, ""
            try:
                status, text = await self._fetch_text(robots_url)
            except Exception as exc:  # noqa: BLE001 - 网络异常统一降级
                self.log.debug("获取 robots.txt 失败 %s: %s", robots_url, exc)
            if status == 404:
                text, status = "User-agent: *\nAllow: /\n", 404
            parser, delay, sitemaps = parse_robots(text, self.user_agent)
            data = _RobotsData(status, parser, delay, sitemaps, time.monotonic())
            self._cache[origin] = data
            self.log.debug("已缓存 robots.txt %s (HTTP %s)", origin, status)
            return data

    async def allowed(self, url: str) -> tuple[bool, str]:
        if not self.enabled:
            return True, "robots 检查已关闭"
        data = await self._get(url)
        if data.status not in {200, 404}:
            if self.on_error == "deny":
                return False, f"无法确认 robots.txt（HTTP {data.status}），保守拒绝"
        try:
            # 保守策略：本 UA 规则组与通配符规则组都必须允许
            ok = data.parser.can_fetch(self.user_agent, url) and data.parser.can_fetch("*", url)
        except Exception:  # noqa: BLE001
            ok = self.on_error == "allow"
        return ok, "" if ok else "robots.txt Disallow"

    async def crawl_delay(self, url: str) -> float:
        if not (self.enabled and self.obey_crawl_delay):
            return 0.0
        data = await self._get(url)
        return data.delay or 0.0

    async def sitemaps(self, url: str) -> list[str]:
        if not self.enabled:
            return []
        data = await self._get(url)
        return list(data.sitemaps)

    def cached_hosts(self) -> list[str]:
        return list(self._cache)
