"""桌面 Web 服务：把引擎包装成本地 REST + SSE 接口。

只监听 127.0.0.1，不对外开放；供 ``desktop/`` 里的桌面窗口使用，
也可被 Java / C++ 版本的同款前端复用（接口契约见 docs/DESKTOP_API.md）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections import deque
from pathlib import Path
from typing import Any

from aiohttp import web

from . import __version__
from .config import Config, ConfigError
from .engine import Crawler

WEB_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "desktop" / "web"
MAX_LOG_LINES = 400
MIME = {".html": "text/html", ".css": "text/css",
        ".js": "application/javascript", ".svg": "image/svg+xml",
        ".ico": "image/x-icon"}


class LogCapture(logging.Handler):
    """把引擎日志收进内存环形缓冲，供桌面窗口展示。"""

    def __init__(self, state: DesktopState) -> None:  # noqa: F821 - 前向引用
        super().__init__(level=logging.DEBUG)
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.state.log(record.levelname, record.getMessage(), record.name)
        except Exception:  # noqa: BLE001 - 日志处理器绝不能影响业务
            pass


class DesktopState:
    """一次桌面会话的全部可变状态。"""

    def __init__(self) -> None:
        self.config: dict[str, Any] = Config.from_dict({}).to_dict()
        self.crawler: Crawler | None = None
        self.task: asyncio.Task | None = None
        self.summary: dict[str, Any] | None = None
        self.error: str = ""
        self.logs: deque[dict[str, str]] = deque(maxlen=MAX_LOG_LINES)
        self._seq = 0
        self._handler = LogCapture(self)
        logging.getLogger("opencrawler").addHandler(self._handler)

    def log(self, level: str, message: str, source: str = "desktop") -> None:
        self._seq += 1
        self.logs.append({"seq": self._seq, "level": level,
                          "message": message, "source": source})

    def logs_since(self, seq: int) -> tuple[int, list[dict]]:
        items = [entry for entry in self.logs if entry["seq"] > seq]
        return self._seq, items

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def status(self) -> dict:
        if self.crawler:
            snap = self.crawler.snapshot()
        else:
            snap = {"running": False, "requests": 0, "succeeded": 0, "failed": 0,
                    "items": 0, "inflight": 0, "frontier": {},
                    "requests_per_second": 0, "adaptive": {"enabled": False}}
        snap.update({
            "version": __version__,
            "running": self.running,
            "summary": self.summary,
            "error": self.error,
            "output_dir": self.config.get("output_dir", "./output"),
        })
        return snap

    def close(self) -> None:
        logging.getLogger("opencrawler").removeHandler(self._handler)


def _json(data: Any, status: int = 200) -> web.Response:
    return web.Response(text=json.dumps(data, ensure_ascii=False, default=str),
                        status=status, content_type="application/json")


def _read_results(config: dict, limit: int) -> list[dict]:
    out = Path(config.get("output_dir", "./output")) / "items.jsonl"
    if not out.is_file():
        return []
    try:
        lines = out.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    items = []
    for line in lines:
        try:
            items.append(json.loads(line))
        except ValueError:
            continue
    return items


async def _static(name: str) -> web.StreamResponse:
    path = WEB_DIR / name
    if not path.is_file():
        return web.Response(status=404, text="not found")
    charset = "utf-8" if path.suffix in {".html", ".css", ".js"} else None
    return web.Response(body=path.read_bytes(),
                        content_type=MIME.get(path.suffix, "application/octet-stream"),
                        charset=charset)


def create_app(state: DesktopState | None = None) -> web.Application:
    """构建桌面服务应用。"""
    st = state or DesktopState()

    async def index(_request: web.Request) -> web.StreamResponse:
        return await _static("index.html")

    async def asset(request: web.Request) -> web.StreamResponse:
        return await _static(request.match_info["name"])

    async def status(_request: web.Request) -> web.Response:
        return _json(st.status())

    async def get_config(_request: web.Request) -> web.Response:
        return _json(st.config)

    async def post_config(request: web.Request) -> web.Response:
        if st.running:
            return _json({"error": "抓取正在运行，请先停止再修改配置"}, 409)
        body = await request.json()
        candidate = {**st.config, **body}
        try:
            cfg = Config.from_dict(candidate)
        except (ConfigError, ValueError) as exc:
            return _json({"error": f"配置无效: {exc}"}, 400)
        st.config = cfg.to_dict()
        st.log("INFO", "配置已更新", "desktop")
        return _json({"ok": True, "config": st.config})

    async def validate(request: web.Request) -> web.Response:
        try:
            cfg = Config.from_dict(await request.json())
            return _json({"valid": True, "warnings": cfg.warnings, "config": cfg.to_dict()})
        except (ConfigError, ValueError) as exc:
            return _json({"valid": False, "error": str(exc)}, 400)

    async def _runner(cfg: Config) -> None:
        crawler = Crawler(cfg)
        st.crawler = crawler
        try:
            st.summary = await crawler.run()
            st.log("INFO", "抓取任务结束", "desktop")
        except asyncio.CancelledError:
            st.log("WARNING", "抓取任务被取消", "desktop")
        except Exception as exc:  # noqa: BLE001 - 桌面任务异常必须落到 UI
            st.error = f"{type(exc).__name__}: {exc}"
            st.log("ERROR", st.error, "desktop")
        finally:
            st.task = None

    async def start(request: web.Request) -> web.Response:
        if st.running:
            return _json({"error": "已有任务在运行"}, 409)
        body = await request.json() if request.can_read_body else {}
        seeds = body.pop("seeds", None) or st.config.get("seeds", [])
        candidate = {**st.config, **body, "seeds": seeds}
        if not candidate["seeds"]:
            return _json({"error": "请先填写至少一个起始 URL"}, 400)
        try:
            cfg = Config.from_dict(candidate)
        except (ConfigError, ValueError) as exc:
            return _json({"error": f"配置无效: {exc}"}, 400)
        st.config, st.summary, st.error = cfg.to_dict(), None, ""
        st.crawler = None
        st.task = asyncio.create_task(_runner(cfg))
        st.log("INFO", f"任务启动：{len(seeds)} 个种子，并发 {cfg.concurrency}", "desktop")
        return _json({"ok": True, "status": st.status()})

    async def stop(_request: web.Request) -> web.Response:
        if not st.running:
            return _json({"ok": True, "message": "当前没有运行中的任务"})
        if st.crawler:
            st.crawler.request_stop("桌面窗口请求停止")
        st.log("WARNING", "已请求优雅停止，正在保存进度…", "desktop")
        return _json({"ok": True})

    async def results(request: web.Request) -> web.Response:
        limit = max(1, min(1000, int(request.query.get("limit", 100))))
        return _json({"items": _read_results(st.config, limit)})

    async def logs(request: web.Request) -> web.Response:
        seq = int(request.query.get("since", 0))
        new_seq, items = st.logs_since(seq)
        return _json({"seq": new_seq, "items": items[-200:]})

    async def export(_request: web.Request) -> web.StreamResponse:
        path = Path(st.config.get("output_dir", "./output")) / "items.jsonl"
        if not path.is_file():
            return web.Response(status=404, text="还没有结果文件")
        return web.FileResponse(path, headers={
            "Content-Disposition": 'attachment; filename="opencrawler-items.jsonl"'})

    async def events(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        })
        await resp.prepare(request)
        seq = 0
        try:
            while True:
                new_seq, items = st.logs_since(seq)
                seq = new_seq
                for entry in items:
                    await resp.write(
                        f"event: log\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n".encode()
                    )
                payload = json.dumps(st.status(), ensure_ascii=False, default=str)
                await resp.write(f"event: status\ndata: {payload}\n\n".encode())
                await asyncio.sleep(1.0)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return resp

    app = web.Application(client_max_size=2 * 1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/{name:app\\.(css|js)}", asset)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", post_config)
    app.router.add_post("/api/validate", validate)
    app.router.add_post("/api/start", start)
    app.router.add_post("/api/stop", stop)
    app.router.add_get("/api/results", results)
    app.router.add_get("/api/logs", logs)
    app.router.add_get("/api/export", export)
    app.router.add_get("/api/events", events)

    async def cleanup(_app: web.Application) -> None:
        if st.running and st.crawler:
            st.crawler.request_stop("桌面服务关闭")
            try:
                await asyncio.wait_for(st.task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if st.task:
                    st.task.cancel()
        st.close()

    app.on_cleanup.append(cleanup)
    return app


def open_desktop_window(url: str) -> bool:
    """用 Edge/Chrome 的 --app 模式打开无地址栏的独立桌面窗口。

    找不到 Chromium 时退回系统默认浏览器；整个过程不依赖任何 GUI 库。
    """
    import shutil
    import subprocess
    import tempfile
    import webbrowser

    candidates = [
        shutil.which("msedge"), shutil.which("chrome"), shutil.which("chromium"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/usr/bin/microsoft-edge", "/usr/bin/google-chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for exe in candidates:
        if not exe or not Path(exe).exists():
            continue
        profile = Path(tempfile.gettempdir()) / "opencrawler-desktop-profile"
        args = [str(exe), f"--app={url}", "--window-size=1320,900",
                f"--user-data-dir={profile}", "--no-first-run",
                "--no-default-browser-check", "--disable-features=Translate"]
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except OSError:
            continue
    return bool(webbrowser.open(url))


async def launch(host: str = "127.0.0.1", port: int = 8756, browser: bool = True) -> None:
    """一键启动：起本地服务，并打开独立桌面窗口。"""
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    url = f"http://{host}:{port}/"
    print(f"OpenCrawlerLab 桌面服务已启动: {url}")
    if browser:
        open_desktop_window(url)
        print("已打开桌面窗口；关闭本窗口或按 Ctrl+C 结束服务。")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def serve(host: str = "127.0.0.1", port: int = 8756) -> None:
    """只启动服务，不打开窗口（供嵌入与自动化测试使用）。"""
    runner = web.AppRunner(create_app())
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    print(f"OpenCrawlerLab 桌面服务已启动: http://{host}:{port}")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
