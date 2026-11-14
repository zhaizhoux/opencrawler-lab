from opencrawler.frontier import Frontier
from opencrawler.models import Request


def test_queue_dedupe_and_resume(tmp_path):
    path = str(tmp_path / "state.sqlite3")
    f = Frontier(path)
    assert f.add(Request("https://a.com/1", priority=5)) is True
    assert f.add(Request("https://a.com/1", priority=9)) is False  # 去重
    assert f.add(Request("https://b.com/1", priority=1)) is True
    assert f.counts()["queued"] == 2

    batch = f.pop_batch(10, per_domain_limit=4, inflight={})
    assert [r.url for r in batch] == ["https://a.com/1", "https://b.com/1"]  # 优先级 + 域名轮转
    assert f.counts()["inflight"] == 2
    f.close()  # 关闭时把 in-flight 还原为 queued -> 断点续爬

    g = Frontier(path)
    assert g.counts()["queued"] == 2
    g.mark_done("https://a.com/1", "hash-1")
    assert g.content_seen("hash-1") and not g.content_seen("hash-2")
    g.close()


def test_per_domain_limit_and_retry(tmp_path):
    f = Frontier(str(tmp_path / "s.sqlite3"))
    f.add_many(Request(f"https://a.com/{i}") for i in range(5))
    batch = f.pop_batch(10, per_domain_limit=2, inflight={"a.com": 1})
    assert len(batch) == 1  # 该域名已有 1 个在途，只剩 1 个配额
    req = batch[0]
    assert f.mark_failed(req, max_attempts=3) is True
    assert req.attempts == 1
    assert f.mark_failed(req, max_attempts=3) is True
    assert f.mark_failed(req, max_attempts=3) is False
    assert f.counts()["failed"] == 1
    f.close()


def test_validators(tmp_path):
    f = Frontier(str(tmp_path / "s.sqlite3"))
    assert f.get_validators("https://a.com/x") == {}
    f.set_validators("https://a.com/x", '"etag"', "Wed, 01 Jan 2026 00:00:00 GMT")
    assert f.get_validators("https://a.com/x")["etag"] == '"etag"'
    f.close()
