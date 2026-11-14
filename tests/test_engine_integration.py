"""端到端测试：内存演示站点 + 完整抓取，验证合规过滤与断点续爬。"""
from __future__ import annotations

import asyncio
import json

from aiohttp import web

from opencrawler.config import Config
from opencrawler.demo import create_app
from opencrawler.engine import Crawler
from opencrawler.frontier import Frontier


class DemoServer:
    async def __aenter__(self):
        self.runner = web.AppRunner(create_app())
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]  # noqa: SLF001
        self.base = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc):
        await self.runner.cleanup()


def _config(base: str, tmp_path) -> Config:
    return Config.from_dict({
        "seeds": [base + "/"],
        "output_dir": str(tmp_path),
        "state_file": str(tmp_path / "state.sqlite3"),
        "concurrency": 8,
        "per_domain_concurrency": 4,
        "default_delay_ms": 0,
        "per_domain_rps": 100,
        "max_pages": 40,
        "max_depth": 3,
        "retries": 1,
        "respect_robots": True,
        "follow_sitemaps": True,
        "log_level": "WARNING",
        "metrics_interval": 1,
    })


def _urls(tmp_path):
    return [
        json.loads(line)["url"]
        for line in (tmp_path / "items.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_end_to_end_compliance(tmp_path):
    async def main():
        async with DemoServer() as server:
            return await Crawler(_config(server.base, tmp_path)).run()

    summary = asyncio.run(main())
    urls = _urls(tmp_path)
    assert len(urls) >= 5, f"抓取页面过少: {urls}"
    assert summary["succeeded"] >= 5
    assert not any(u.rstrip("/").endswith("/secret") for u in urls), "不应抓取 robots 禁止页"
    assert not any("/admin/" in u for u in urls), "不应抓取管理页"
    assert not any("example.org" in u for u in urls), "默认不应抓外链"
    assert any(u.endswith("/sitemap.xml") for u in urls), "应跟随 robots.txt 中的 Sitemap"


def test_resume_is_idempotent(tmp_path):
    async def main():
        async with DemoServer() as server:
            first = await Crawler(_config(server.base, tmp_path)).run()
            second = await Crawler(_config(server.base, tmp_path)).run()
            return first, second

    first, second = asyncio.run(main())
    assert first["requests"] >= 5
    assert second["requests"] == 0, "已完成的 URL 不应重复抓取"
    assert second["stop_reason"] == "队列已清空"


def test_interrupted_task_is_resumed(tmp_path):
    async def main():
        async with DemoServer() as server:
            cfg = _config(server.base, tmp_path)
            await Crawler(cfg).run()
            # 模拟进程被强杀：把一个已完成页面重新置为「进行中」
            frontier = Frontier(cfg.state_file, resume=False)
            target = server.base + "/page/2"
            frontier.db.execute(
                "UPDATE frontier SET state=1 WHERE url=?", (target,)
            )
            frontier.db.commit()
            frontier.db.close()
            return await Crawler(cfg).run()

    summary = asyncio.run(main())
    assert summary["requests"] == 1, "中断的任务应被重新入队且只重跑一次"
