"""爬虫内部数据模型。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .utils import decode_body, normalize_url, now_iso


@dataclass(slots=True)
class Request:
    """一个待抓取任务。序列化后可直接存入 SQLite 队列，支持断点续爬。"""

    url: str
    depth: int = 0
    priority: int = 0
    kind: str = "page"  # page | sitemap | feed | asset | custom
    headers: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0

    def __post_init__(self) -> None:
        self.url = normalize_url(self.url) or self.url

    @property
    def key(self) -> str:
        return self.url

    def to_json(self) -> str:
        return json.dumps(
            {
                "url": self.url, "depth": self.depth, "priority": self.priority,
                "kind": self.kind, "headers": self.headers, "meta": self.meta,
                "attempts": self.attempts,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "Request":
        data = json.loads(raw)
        return cls(
            url=data["url"], depth=int(data.get("depth", 0)),
            priority=int(data.get("priority", 0)), kind=data.get("kind", "page"),
            headers=dict(data.get("headers") or {}), meta=dict(data.get("meta") or {}),
            attempts=int(data.get("attempts", 0)),
        )


@dataclass(slots=True)
class Response:
    request: Request
    status: int
    final_url: str
    headers: dict[str, str]
    body: bytes
    elapsed_ms: int = 0
    content_type: str = ""
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        return decode_body(self.body, self.content_type)

    @property
    def size(self) -> int:
        return len(self.body)


@dataclass(slots=True)
class Item:
    """交付给 Pipeline 的一条结构化数据。"""

    data: dict[str, Any]
    url: str
    kind: str = "page"
    content_hash: str = ""
    crawled_at: str = field(default_factory=now_iso)

    def to_json(self) -> str:
        return json.dumps(
            {
                "url": self.url, "kind": self.kind, "content_hash": self.content_hash,
                "crawled_at": self.crawled_at, "data": self.data,
            },
            ensure_ascii=False,
        )


@dataclass(slots=True)
class ExtractResult:
    item: dict[str, Any] = field(default_factory=dict)
    links: list[Request] = field(default_factory=list)
    content_hash: str = ""
    skip: bool = False
    reason: str = ""
