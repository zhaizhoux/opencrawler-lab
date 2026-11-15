"""极简高层 API 的测试（不发出公网请求）。"""
import pytest

from opencrawler import Session, __version__, crawl, plan
from opencrawler.config import ConfigError


def test_version_bumped():
    assert __version__ == "0.3.0"


def test_plan_does_not_touch_network():
    result = plan("https://example.com/", max_pages=7)
    assert result["dry_run"] is True
    assert result["config"]["max_pages"] == 7
    assert result["seeds"] == ["https://example.com/"]


def test_session_rejects_bad_options_early():
    with pytest.raises((ConfigError, ValueError)):
        Session(storage="not-a-backend")


def test_session_accepts_multiple_seeds_and_overrides():
    urls = ["https://a.example/", "https://b.example/"]
    s = Session(dry_run=True)
    report = s.run(urls, max_pages=3)
    assert report["seeds"] == urls
    assert report["config"]["max_pages"] == 3
    assert len(s.reports) == 1
    assert s.last_crawler is not None


def test_crawl_one_liner_with_string_seed():
    report = crawl("https://example.com/", dry_run=True, max_pages=1)
    assert report["seeds"] == ["https://example.com/"]
    assert report["config"]["adaptive_concurrency"] is True


def test_context_manager_protocol():
    with Session(dry_run=True) as s:
        assert s.run(["https://example.com/"])["dry_run"] is True
