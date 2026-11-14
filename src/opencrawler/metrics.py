"""运行指标：请求量、状态分布、流量、队列、去重、错误与实时速率。"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Metrics:
    started_at: float = field(default_factory=time.monotonic)
    requests: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    not_modified: int = 0
    items: int = 0
    duplicates: int = 0
    links: int = 0
    retries: int = 0
    bytes_downloaded: int = 0
    status_codes: Counter = field(default_factory=Counter)
    domains: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)

    def record_response(self, url: str, status: int, size: int, host: str) -> None:
        self.requests += 1
        self.status_codes[status] += 1
        self.domains[host] += 1
        self.bytes_downloaded += size
        if 200 <= status < 300:
            self.succeeded += 1

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def rps(self) -> float:
        return self.requests / max(self.elapsed(), 0.001)

    def snapshot(self, *, counts: dict[str, int] | None = None, inflight: int = 0) -> dict:
        return {
            "elapsed_seconds": round(self.elapsed(), 1),
            "requests": self.requests,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "not_modified": self.not_modified,
            "items": self.items,
            "duplicates": self.duplicates,
            "links_discovered": self.links,
            "bytes": self.bytes_downloaded,
            "requests_per_second": round(self.rps(), 2),
            "status_codes": dict(self.status_codes),
            "domains": dict(self.domains.most_common(10)),
            "top_errors": dict(self.errors.most_common(5)),
            "frontier": counts or {},
            "inflight": inflight,
        }

    def render(self, *, counts: dict[str, int] | None = None, inflight: int = 0) -> str:
        snap = self.snapshot(counts=counts, inflight=inflight)
        queue = counts or {}
        return (
            f"[{snap['elapsed_seconds']:>7.1f}s] 请求 {snap['requests']} | 成功 {snap['succeeded']} | "
            f"失败 {snap['failed']} | 条目 {snap['items']} | 去重 {snap['duplicates']} | "
            f"{snap['requests_per_second']:.2f} req/s | "
            f"队列 {queue.get('queued', 0)} / 进行中 {inflight} / 完成 {queue.get('done', 0)}"
        )

    def write(self, path: str | Path, *, counts: dict[str, int], inflight: int) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(self.snapshot(counts=counts, inflight=inflight), ensure_ascii=False) + "\n")
