"""桌面服务 REST / SSE 端到端测试：使用 aiohttp 自带测试客户端，不打开窗口。"""
import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from opencrawler.server import DesktopState, create_app


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


def test_info_endpoint_identifies_implementation():
    async def scenario():
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            info = await (await client.get("/api/info")).json()
            assert info["implementation"] == "python"
            assert info["version"] == "0.3.0"
            assert "/api/events" in info["endpoints"]
            assert "遵守 robots.txt" in info["compliance_defaults"]
            status = await (await client.get("/api/status")).json()
            assert status["implementation"] == "python"
            assert status["uptime_seconds"] >= 0
            for key in ("skipped", "duplicates", "bytes", "links_discovered",
                        "requests_per_second", "frontier", "adaptive"):
                assert key in status
    _run(scenario())


def test_results_query_filter_and_pagination(tmp_path):
    rows = [
        {"url": "https://a.test/one", "kind": "page",
         "data": {"title": "Alpha", "status": 200}},
        {"url": "https://a.test/two", "kind": "sitemap",
         "data": {"title": "Sitemap", "status": 200}},
        {"url": "https://a.test/three", "kind": "page",
         "data": {"title": "Beta", "status": 404}},
    ]
    (tmp_path / "items.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    async def scenario():
        state = DesktopState()
        state.config["output_dir"] = str(tmp_path)
        app = create_app(state)
        async with TestClient(TestServer(app)) as client:
            all_rows = await (await client.get("/api/results")).json()
            assert all_rows["total"] == 3 and len(all_rows["items"]) == 3
            pages = await (await client.get("/api/results?kind=page")).json()
            assert pages["total"] == 2
            assert [r["url"] for r in pages["items"]] == [
                "https://a.test/one", "https://a.test/three"]
            hits = await (await client.get("/api/results?q=alpha")).json()
            assert hits["total"] == 1 and hits["items"][0]["data"]["title"] == "Alpha"
            older = await (await client.get("/api/results?limit=2&offset=1")).json()
            assert older["total"] == 3
            assert [r["url"] for r in older["items"]] == [
                "https://a.test/one", "https://a.test/two"]
    _run(scenario())


def test_validate_contract_uses_valid_false():
    async def scenario():
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            bad = await client.post("/api/validate", json={"storage": "wrong"})
            assert bad.status == 400
            payload = await bad.json()
            assert payload["valid"] is False and payload["error"]
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
