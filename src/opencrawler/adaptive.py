"""AIMD 自适应并发控制。

固定并发数在生产环境往往不是最优：目标站慢时要主动收敛（避免拖垮站点、避免
429），目标站快时应逐步试探更高吞吐。本模块用一个滑动窗口的成功率与 p95 延迟
驱动「乘性减、加性增」，并且只调整上限，不干预任何单域名礼貌限速。

设计要点：
* 并发上限只在样本足够且冷却期结束后调整，避免抖动；
* 错误率或延迟越界时乘性下降到 80%，否则按 1/8 逐步加性增加；
* 下限保证长时任务不会退化为完全停摆，上限不超过配置并发数的 4 倍。
"""
from __future__ import annotations

import time
from collections import deque


class AdaptiveConcurrency:
    """根据最近窗口的观测值动态给出建议并发数。

    ``probe_interval=0`` 可用于单元测试（每次凑够样本立即调整）。
    """

    def __init__(
        self,
        initial: int,
        *,
        minimum: int = 2,
        maximum: int | None = None,
        target_latency_ms: float = 1200.0,
        error_threshold: float = 0.15,
        window: int = 30,
        probe_interval: float = 2.0,
    ) -> None:
        self.initial = max(1, int(initial))
        self.minimum = max(1, min(minimum, self.initial))
        self.maximum = maximum or self.initial * 4
        self.target_latency_ms = float(target_latency_ms)
        self.error_threshold = float(error_threshold)
        self.window = max(4, int(window))
        self.probe_interval = float(probe_interval)
        self.limit = self.initial
        self._samples: deque[tuple[float, bool]] = deque(maxlen=self.window)
        self._last_adjust = 0.0
        self.adjustments = 0

    def record(self, latency_ms: float, ok: bool) -> None:
        """记录一次请求结果；必要时重新计算并发上限。"""
        self._samples.append((max(0.0, float(latency_ms)), bool(ok)))
        if len(self._samples) < self.window:
            return
        now = time.monotonic()
        if self.probe_interval and now - self._last_adjust < self.probe_interval:
            return
        self._last_adjust = now

        errors = sum(1 for _, good in self._samples if not good)
        error_rate = errors / len(self._samples)
        latencies = sorted(lat for lat, _ in self._samples)
        p95 = latencies[int(0.95 * (len(latencies) - 1))]

        if error_rate > self.error_threshold or p95 > self.target_latency_ms * 1.5:
            new_limit = max(self.minimum, int(self.limit * 0.8))
        elif error_rate < self.error_threshold / 2 and p95 < self.target_latency_ms:
            new_limit = min(self.maximum, self.limit + max(1, self.limit // 8))
        else:
            new_limit = self.limit
        if new_limit != self.limit:
            self.limit = new_limit
            self.adjustments += 1
        self._samples.clear()

    def snapshot(self) -> dict:
        return {
            "enabled": True,
            "limit": self.limit,
            "initial": self.initial,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "target_latency_ms": self.target_latency_ms,
            "adjustments": self.adjustments,
            "samples_in_window": len(self._samples),
        }
