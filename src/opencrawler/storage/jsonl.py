"""JSONL 追加写：每行一条完整记录，便于流式处理与大数据管道对接。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TextIO

from ..config import Config
from ..models import Item
from . import Storage


class JsonlStorage(Storage):
    def __init__(self, config: Config) -> None:
        self.cfg = config
        out = Path(config.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.path = out / "items.jsonl"
        self.raw_dir = out / "raw"
        if config.save_raw:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO = self.path.open("a", encoding="utf-8")

    async def write(self, item: Item) -> None:
        self._fh.write(item.to_json() + "\n")
        self._fh.flush()  # 长时间运行时保证数据落盘
        if self.cfg.save_raw:
            digest = hashlib.sha1(item.url.encode("utf-8")).hexdigest()[:20]
            (self.raw_dir / f"{digest}.json").write_text(
                item.to_json(), encoding="utf-8"
            )

    async def close(self) -> None:
        self._fh.close()
