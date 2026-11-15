"""AIMD 自适应并发的确定性单元测试。"""
from opencrawler.adaptive import AdaptiveConcurrency


def test_fast_success_raises_limit():
    a = AdaptiveConcurrency(16, window=10, probe_interval=0, target_latency_ms=1000)
    for _ in range(10):
        a.record(50.0, True)
    assert a.limit > 16
    assert a.adjustments == 1


def test_high_error_rate_reduces_limit():
    a = AdaptiveConcurrency(32, window=10, probe_interval=0, error_threshold=0.1)
    for _ in range(10):
        a.record(50.0, False)
    assert a.limit == int(32 * 0.8)
    assert a.limit >= a.minimum


def test_high_latency_reduces_limit_even_when_successful():
    a = AdaptiveConcurrency(32, window=10, probe_interval=0, target_latency_ms=100)
    for _ in range(10):
        a.record(500.0, True)
    assert a.limit < 32


def test_never_exceeds_bounds():
    a = AdaptiveConcurrency(8, minimum=2, maximum=10, window=4, probe_interval=0)
    for _ in range(200):
        a.record(1.0, True)
    assert a.limit == 10
    b = AdaptiveConcurrency(8, minimum=2, maximum=10, window=4, probe_interval=0)
    for _ in range(200):
        b.record(1.0, False)
    assert b.limit == 2


def test_window_must_be_full_before_adjusting():
    a = AdaptiveConcurrency(16, window=10, probe_interval=0)
    for _ in range(9):
        a.record(1.0, True)
    assert a.limit == 16
    a.record(1.0, True)
    assert a.limit > 16


def test_snapshot_shape():
    snap = AdaptiveConcurrency(8).snapshot()
    assert snap["enabled"] is True
    assert {"limit", "initial", "minimum", "maximum", "adjustments"} <= set(snap)
