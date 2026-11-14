"""输出管线：内容去重 -> 自定义中间件/插件 -> 存储后端。"""
from __future__ import annotations

import logging
from typing import Any

from .config import Config
from .frontier import Frontier
from .models import Item, Request, Response
from .plugins import load_callable, maybe_await
from .storage import create_storage


class MiddlewareChain:
    """中间件协议：callable(request, response=None) -> bool/Request/Response/None。

    抓取前 response=None，抓取后传入 response；返回 False 表示丢弃该任务。
    """

    def __init__(self, specs: list[str], logger: logging.Logger | None = None) -> None:
        self.log = logger or logging.getLogger("opencrawler.middleware")
        self.hooks = []
        for spec in specs:
            try:
                self.hooks.append(load_callable(spec))
            except (ImportError, AttributeError, ValueError, TypeError) as exc:
                self.log.warning("加载中间件 %s 失败: %s", spec, exc)

    async def before(self, request: Request) -> bool:
        for hook in self.hooks:
            try:
                result = await maybe_await(hook(request, None))
                if result is False:
                    return False
                if isinstance(result, Request):
                    request.url = result.url
                    request.headers.update(result.headers)
            except Exception as exc:  # noqa: BLE001
                self.log.warning("中间件异常 %s: %s", hook, exc)
        return True

    async def after(self, request: Request, response: Response) -> bool:
        for hook in self.hooks:
            try:
                result = await maybe_await(hook(request, response))
                if result is False:
                    return False
            except Exception as exc:  # noqa: BLE001
                self.log.warning("中间件异常 %s: %s", hook, exc)
        return True


class PipelineManager:
    def __init__(
        self, config: Config, frontier: Frontier | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.cfg = config
        self.frontier = frontier
        self.log = logger or logging.getLogger("opencrawler.pipeline")
        self.storage = create_storage(config)
        self.hooks: list[Any] = []
        for spec in config.pipelines:
            try:
                self.hooks.append(load_callable(spec))
            except (ImportError, AttributeError, ValueError, TypeError) as exc:
                self.log.warning("加载输出插件 %s 失败: %s", spec, exc)

    async def process(self, item: Item) -> tuple[bool, str]:
        if self.cfg.dedupe_content and self.frontier and self.frontier.content_seen(item.content_hash):
            return False, "内容重复"
        for hook in self.hooks:
            try:
                result = await maybe_await(hook(item))
            except Exception as exc:  # noqa: BLE001
                self.log.warning("输出插件异常 %s: %s", hook, exc)
                continue
            if result is False:
                return False, "插件丢弃"
            if isinstance(result, Item):
                item = result
            elif isinstance(result, dict):
                item.data.update(result)
        await self.storage.write(item)
        return True, ""

    async def close(self) -> None:
        await self.storage.close()
