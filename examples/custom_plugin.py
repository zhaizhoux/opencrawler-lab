"""三个扩展点的最小示例。

在配置里这样引用（路径相对项目根目录，或写成 "包名.模块:函数"）：
    parsers:     ["examples.custom_plugin:parse_private_api"]
    pipelines:   ["examples.custom_plugin:add_language"]
    middlewares: ["examples.custom_plugin:skip_tracking_params"]
"""
from __future__ import annotations

import json
from typing import Any

from opencrawler.models import ExtractResult, Item, Request, Response


# 1) 自定义解析器：返回非空结果即接管该响应的解析
def parse_private_api(response: Response) -> ExtractResult | None:
    if "application/json" not in response.content_type:
        return None
    try:
        data = json.loads(response.text)
    except ValueError:
        return None
    if not isinstance(data, dict) or "records" not in data:
        return None  # 交回内置抽取器
    records = data["records"]
    return ExtractResult(
        item={
            "url": response.final_url,
            "record_count": len(records),
            "records": records[:20],
            "source": "custom-parser",
        },
        links=[],
    )


# 2) 输出插件：返回 False 丢弃，返回 dict 合并，返回 Item 替换
def add_language(item: Item) -> dict[str, Any] | bool:
    if item.data.get("kind") == "sitemap":
        return False  # 示例：不落盘 sitemap 本身
    return {"language": item.data.get("lang", "unknown"), "processed_by": "custom_plugin"}


# 3) 中间件：抓取前 response=None；抓取后传入 response；返回 False 丢弃
def skip_tracking_params(request: Request, response: Response | None = None):
    if response is None and "fbclid=" in request.url:
        return False
    if response is not None and response.size > 2_000_000:
        return False
    return True
