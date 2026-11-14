import asyncio
import time

from opencrawler.ratelimit import DomainLimiter
from opencrawler.robots import RobotsPolicy, parse_robots

ROBOTS = """User-agent: *
Disallow: /private
Crawl-delay: 1
Sitemap: https://example.com/sitemap.xml

User-agent: OpenCrawlerLab
Disallow: /lab-only
Crawl-delay: 2
"""


async def _fake_fetch(url: str):
    return 200, ROBOTS


def test_parse_robots_groups():
    parser, delay, sitemaps = parse_robots(ROBOTS, "OpenCrawlerLab/0.1")
    # 标准语义：UA 命中专属组时，只应用该组规则；本框架在策略层再叠加通配组做保守合并
    assert parser.can_fetch("OpenCrawlerLab/0.1", "https://example.com/public") is True
    assert parser.can_fetch("*", "https://example.com/private/x") is False
    assert parser.can_fetch("OpenCrawlerLab/0.1", "https://example.com/lab-only/x") is False
    assert delay == 2.0
    assert sitemaps == ["https://example.com/sitemap.xml"]


def test_policy_allow_deny_sitemap_delay():
    async def main():
        policy = RobotsPolicy(_fake_fetch, user_agent="OpenCrawlerLab/0.1", obey_crawl_delay=True)
        assert (await policy.allowed("https://example.com/ok"))[0] is True
        assert (await policy.allowed("https://example.com/private/x"))[0] is False
        assert (await policy.allowed("https://example.com/lab-only/x"))[0] is False
        assert await policy.crawl_delay("https://example.com/ok") == 2.0
        assert await policy.sitemaps("https://example.com/ok") == ["https://example.com/sitemap.xml"]
        assert policy.cached_hosts() == ["https://example.com"]
    asyncio.run(main())


def test_policy_fail_closed_on_error():
    async def fail(url):
        return 503, ""
    async def main():
        p = RobotsPolicy(fail, on_error="deny")
        assert (await p.allowed("https://example.com/x"))[0] is False
        p2 = RobotsPolicy(fail, on_error="allow")
        assert (await p2.allowed("https://example.com/x"))[0] is True
    asyncio.run(main())


def test_domain_limiter_serializes_and_penalizes():
    async def main():
        limiter = DomainLimiter(default_delay_ms=40, per_domain_rps=100, per_domain_concurrency=2)
        started = time.monotonic()
        async with limiter.slot("a.com"):
            pass
        async with limiter.slot("a.com"):
            pass
        assert time.monotonic() - started >= 0.035
        limiter.penalize("a.com", 0.06)
        started = time.monotonic()
        async with limiter.slot("a.com"):
            pass
        assert time.monotonic() - started >= 0.05
        assert limiter.stats()["penalized"] == 0 or limiter.stats()["domains"] == 1
    asyncio.run(main())
