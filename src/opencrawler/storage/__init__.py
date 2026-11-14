"""存储后端抽象与工厂。"""
from __future__ import annotations

from ..config import Config
from ..models import Item


class Storage:
    async def write(self, item: Item) -> None:  # pragma: no cover - 接口
        raise NotImplementedError

    async def close(self) -> None:
        return None


class NullStorage(Storage):
    async def write(self, item: Item) -> None:
        return None


def create_storage(config: Config) -> Storage:
    if config.storage == "jsonl":
        from .jsonl import JsonlStorage
        return JsonlStorage(config)
    if config.storage == "sqlite":
        from .sqlite import SqliteStorage
        return SqliteStorage(config)
    return NullStorage()
