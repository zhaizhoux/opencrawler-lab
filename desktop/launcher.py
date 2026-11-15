"""OpenCrawlerLab 一键启动入口：启动本地服务并打开独立桌面窗口。

    python desktop/launcher.py                 # 默认 127.0.0.1:8756
    python desktop/launcher.py --port 9000 --no-browser

也是 PyInstaller 打包成 OpenCrawlerLab.exe 的入口，不需要任何 GUI 库。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

try:  # 源码运行：把 src/ 加入模块搜索路径
    ROOT = Path(__file__).resolve().parents[1]
    if (ROOT / "src" / "opencrawler").is_dir():
        sys.path.insert(0, str(ROOT / "src"))
except NameError:  # pragma: no cover - 冻结环境下 __file__ 仍存在
    pass

from opencrawler.server import launch  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenCrawlerLab 桌面应用")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument("--no-browser", action="store_true", help="只启动服务")
    args = parser.parse_args()
    try:
        asyncio.run(launch(args.host, args.port, browser=not args.no_browser))
    except KeyboardInterrupt:
        print("\n桌面服务已关闭。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
