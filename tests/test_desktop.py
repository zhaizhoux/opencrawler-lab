"""桌面服务 REST / SSE 端到端测试：使用 aiohttp 自带测试客户端，不打开窗口。"""
import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from opencrawler.server import create_app


def _run(coro):
    return asyncio.run(coro)


def test_static_assets_and_status():
    async def scenario():
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            html = await client.get("/")
            assert html.status == 200
            assert "OpenCrawlerLab" in await html.text()
            assert (await client.get("/app.css")).status == 200
            assert (await client.get("/app.js")).status == 200
            status = await (await client.get("/api/status")).json()
            assert status["running"] is False
            assert "version" in status
    _run(scenario())


def test_config_validate_and_persistence():
    async def scenario():
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            before = await (await client.get("/api/config")).json()
            assert before["respect_robots"] is True
            resp = await client.post("/api/validate", json={"max_pages": 10})
            assert (await resp.json())["valid"] is True
            bad = await client.post("/api/validate", json={"storage": "wrong"})
            assert bad.status == 400
            changed = await client.post("/api/config", json={"max_pages": 42})
            assert (await changed.json())["config"]["max_pages"] == 42
            after = await (await client.get("/api/config")).json()
            assert after["max_pages"] == 42
    _run(scenario())


def test_start_stop_and_results_api():
    async def scenario():
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            missing = await client.post("/api/start", json={"seeds": []})
            assert missing.status == 400
            started = await client.post("/api/start", json={
                "seeds": ["https://example.com/"], "dry_run": True,
            })
            assert started.status == 200, await started.text()
            st = await (await client.get("/api/status")).json()
            assert st["version"]
            # dry-run 任务会迅速结束，stop 接口在两种状态下都应安全
            assert (await client.post("/api/stop")).status == 200
            results = await (await client.get("/api/results?limit=10")).json()
            assert "items" in results
            logs = await (await client.get("/api/logs")).json()
            assert "items" in logs and "seq" in logs
    _run(scenario())


def test_sse_emits_status_frame():
    async def scenario():
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/events")
            assert resp.status == 200
            assert resp.headers["Content-Type"].startswith("text/event-stream")
            chunk = await resp.content.read(4096)
            text = chunk.decode("utf-8", "replace")
            assert "event: status" in text
            assert json.loads(text.split("data: ", 1)[1].split("\n\n", 1)[0])["version"]
            resp.close()
    _run(scenario())
