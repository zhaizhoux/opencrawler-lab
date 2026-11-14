"""按域名限速：最小请求间隔 + 并发槽位 + 429/5xx 自适应退避。"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass(slots=True)
class _DomainState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    semaphore: asyncio.Semaphore | None = None
    next_allowed: float = 0.0
    penalty_until: float = 0.0


class DomainLimiter:
    """每个域名独立的令牌间隔控制与并发上限。

    interval = max(默认间隔, 域名定制间隔, Crawl-delay, 1000/每域 RPS)
    """

    def __init__(
        self,
        *,
        default_delay_ms: int = 500,
        per_domain_delay_ms: dict[str, int] | None = None,
        per_domain_rps: float = 2.0,
        per_domain_concurrency: int = 4,
    ) -> None:
        self.default_delay_ms = default_delay_ms
        self.per_domain_delay_ms = per_domain_delay_ms or {}
        self.rps_interval = 1.0 / max(per_domain_rps, 0.001)
        self.per_domain_concurrency = max(1, per_domain_concurrency)
        self._states: dict[str, _DomainState] = {}

    def _state(self, host: str) -> _DomainState:
        state = self._states.get(host)
        if state is None:
            state = _DomainState(semaphore=asyncio.Semaphore(self.per_domain_concurrency))
            self._states[host] = state
        return state

    def interval(self, host: str, extra_delay_ms: float = 0.0) -> float:
        custom = self.per_domain_delay_ms.get(host, 0)
        return max(
            self.default_delay_ms / 1000.0,
            custom / 1000.0,
            extra_delay_ms / 1000.0,
            self.rps_interval,
        )

    @asynccontextmanager
    async def slot(self, host: str, extra_delay_ms: float = 0.0):
        state = self._state(host)
        interval = self.interval(host, extra_delay_ms)
        # 只在「分配出发时间」时持锁，休眠放到锁外：
        # 否则高并发下同域请求会被锁内 sleep 完全串行化，并发度形同虚设。
        async with state.lock:
            now = time.monotonic()
            target = max(state.next_allowed, state.penalty_until, now)
            wait = target - now
            state.next_allowed = target + interval
        if wait > 0:
            await asyncio.sleep(wait)
        assert state.semaphore is not None
        async with state.semaphore:
            yield

    def penalize(self, host: str, seconds: float) -> None:
        """遇到 429 / Retry-After 时临时封停该域名。"""
        state = self._state(host)
        state.penalty_until = max(state.penalty_until, time.monotonic() + seconds)

    def stats(self) -> dict[str, float]:
        return {
            "domains": len(self._states),
            "penalized": sum(1 for s in self._states.values() if s.penalty_until > time.monotonic()),
        }
