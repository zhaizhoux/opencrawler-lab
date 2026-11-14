"""基于 SQLite 的持久化优先队列：去重、断点续爬、按域名公平调度。

所有状态都落盘，进程被 Ctrl+C / 崩溃后重新运行即可继续，不会重复抓取。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable

from .models import Request
from .utils import host_of, now_ms

_SCHEMA = """
CREATE TABLE IF NOT EXISTS frontier (
    url        TEXT PRIMARY KEY,
    host       TEXT NOT NULL,
    depth      INTEGER NOT NULL DEFAULT 0,
    priority   INTEGER NOT NULL DEFAULT 0,
    kind       TEXT NOT NULL DEFAULT 'page',
    payload    TEXT NOT NULL,
    state      INTEGER NOT NULL DEFAULT 0,  -- 0 待抓 / 1 进行中 / 2 完成 / 3 失败
    attempts   INTEGER NOT NULL DEFAULT 0,
    note       TEXT NOT NULL DEFAULT '',
    added_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_frontier_state ON frontier(state, priority DESC, added_at);
CREATE INDEX IF NOT EXISTS idx_frontier_host ON frontier(host, state);
CREATE TABLE IF NOT EXISTS content_hashes (
    hash TEXT PRIMARY KEY,
    url  TEXT NOT NULL,
    seen_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS validators (
    url            TEXT PRIMARY KEY,
    etag           TEXT,
    last_modified  TEXT
);
"""

QUEUED, INFLIGHT, DONE, FAILED = 0, 1, 2, 3


class Frontier:
    def __init__(self, path: str, *, resume: bool = True) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(p)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(_SCHEMA)
        if resume:
            self.requeue_inflight()
        self.db.commit()

    # ---------------- 入队 ----------------
    def add(self, request: Request) -> bool:
        return self.add_many([request]) == 1

    def add_many(self, requests: Iterable[Request]) -> int:
        rows = []
        for req in requests:
            rows.append(
                (
                    req.url, host_of(req.url), req.depth, req.priority, req.kind,
                    req.to_json(), QUEUED, req.attempts, "", now_ms(),
                )
            )
        if not rows:
            return 0
        before = self.db.total_changes
        self.db.executemany(
            "INSERT OR IGNORE INTO frontier"
            "(url, host, depth, priority, kind, payload, state, attempts, note, added_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.db.commit()
        return self.db.total_changes - before

    # ---------------- 出队 ----------------
    def pop_batch(self, limit: int, *, per_domain_limit: int, inflight: dict[str, int]) -> list[Request]:
        """按优先级取任务，并在多个域名之间轮转，保证公平与每域并发上限。"""
        if limit <= 0:
            return []
        rows = self.db.execute(
            "SELECT * FROM frontier WHERE state=? ORDER BY priority DESC, added_at ASC, rowid ASC LIMIT ?",
            (QUEUED, max(64, limit * 8)),
        ).fetchall()
        buckets: dict[str, deque] = defaultdict(deque)
        for row in rows:
            buckets[row["host"]].append(row)

        selected: list[sqlite3.Row] = []
        assigned: dict[str, int] = defaultdict(int)
        while len(selected) < limit:
            progressed = False
            for host, queue in list(buckets.items()):
                if not queue:
                    continue
                if inflight.get(host, 0) + assigned[host] >= per_domain_limit:
                    continue
                selected.append(queue.popleft())
                assigned[host] += 1
                progressed = True
                if len(selected) >= limit:
                    break
            if not progressed:
                break
        if selected:
            self.db.executemany(
                "UPDATE frontier SET state=? WHERE url=?",
                [(INFLIGHT, row["url"]) for row in selected],
            )
            self.db.commit()
        return [Request.from_json(row["payload"]) for row in selected]

    # ---------------- 状态回写 ----------------
    def mark_done(self, url: str, content_hash: str = "", note: str = "") -> None:
        self.db.execute(
            "UPDATE frontier SET state=?, note=? WHERE url=?", (DONE, note, url)
        )
        if content_hash:
            self.db.execute(
                "INSERT OR IGNORE INTO content_hashes(hash,url,seen_at) VALUES (?,?,?)",
                (content_hash, url, now_ms()),
            )
        self.db.commit()

    def mark_failed(self, request: Request, max_attempts: int, note: str = "") -> bool:
        """返回 True 表示已重新入队，False 表示最终失败。"""
        attempts = request.attempts + 1
        if attempts < max_attempts:
            request.attempts = attempts
            request.priority -= 1
            self.db.execute(
                "UPDATE frontier SET state=?, attempts=?, priority=?, payload=?, note=? WHERE url=?",
                (QUEUED, attempts, request.priority, request.to_json(), note, request.url),
            )
            retry = True
        else:
            self.db.execute(
                "UPDATE frontier SET state=?, attempts=?, note=? WHERE url=?",
                (FAILED, attempts, note, request.url),
            )
            retry = False
        self.db.commit()
        return retry

    def requeue_inflight(self) -> int:
        cur = self.db.execute("UPDATE frontier SET state=? WHERE state=?", (QUEUED, INFLIGHT))
        return cur.rowcount

    def content_seen(self, content_hash: str) -> bool:
        if not content_hash:
            return False
        return self.db.execute(
            "SELECT 1 FROM content_hashes WHERE hash=?", (content_hash,)
        ).fetchone() is not None

    # ---------------- 条件请求 ----------------
    def get_validators(self, url: str) -> dict[str, str]:
        row = self.db.execute("SELECT * FROM validators WHERE url=?", (url,)).fetchone()
        if not row:
            return {}
        return {k: row[k] for k in ("etag", "last_modified") if row[k]}

    def set_validators(self, url: str, etag: str = "", last_modified: str = "") -> None:
        self.db.execute(
            "INSERT INTO validators(url,etag,last_modified) VALUES (?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET etag=excluded.etag, last_modified=excluded.last_modified",
            (url, etag, last_modified),
        )
        self.db.commit()

    # ---------------- 维护 ----------------
    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT state, COUNT(*) AS n FROM frontier GROUP BY state").fetchall()
        result = {"queued": 0, "inflight": 0, "done": 0, "failed": 0, "total": 0}
        keys = {QUEUED: "queued", INFLIGHT: "inflight", DONE: "done", FAILED: "failed"}
        for row in rows:
            result[keys.get(row["state"], "failed")] = row["n"]
            result["total"] += row["n"]
        return result

    def reset(self) -> None:
        self.db.executescript(
            "DELETE FROM frontier; DELETE FROM content_hashes; DELETE FROM validators;"
        )
        self.db.commit()

    def close(self) -> None:
        self.requeue_inflight()
        self.db.commit()
        self.db.close()
