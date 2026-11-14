"""扩展点：从 "模块:函数" 或 "文件路径.py:函数" 动态加载插件。"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
from pathlib import Path
from typing import Any, Callable


def load_callable(spec: str) -> Callable[..., Any]:
    if not isinstance(spec, str) or ":" not in spec:
        raise ValueError(f"插件格式应为 '模块:函数' 或 '路径.py:函数'，收到: {spec!r}")
    target, attr = spec.split(":", 1)
    target, attr = target.strip(), attr.strip()
    module: Any
    if target.endswith(".py") or Path(target).is_file():
        path = Path(target).resolve()
        name = f"opencrawler_plugin_{path.stem}_{abs(hash(str(path)))}"
        module_spec = importlib.util.spec_from_file_location(name, path)
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"无法加载插件文件: {path}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    obj: Any = module
    for part in attr.split("."):
        obj = getattr(obj, part)
    if not callable(obj):
        raise TypeError(f"插件 {spec} 不是可调用对象")
    return obj


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
