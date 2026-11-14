"""SQLite 结构化存储：单表 + 索引，便于 SQL 查询与增量分析。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import Config
from ..models import Item
from . import Storage


class SqliteStorage(Storage):
    def __init__(self, config: Config) -> None:
        out = Path(config.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(out / "items.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS items (
                url TEXT PRIMARY KEY,
                kind TEXT,
                content_hash TEXT,
                crawled_at TEXT,
                data TEXT NOT NULL
            )"""
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_items_hash ON items(content_hash)")
        self.db.commit()

    async def write(self, item: Item) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO items(url,kind,content_hash,crawled_at,data) VALUES (?,?,?,?,?)",
            (item.url, item.kind, item.content_hash, item.crawled_at,
             __import__("json").dumps(item.data, ensure_ascii=False)),
        )
        self.db.commit()

    async def close(self) -> None:
        self.db.close()
