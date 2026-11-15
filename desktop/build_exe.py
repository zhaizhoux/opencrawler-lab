"""把桌面应用打包成单文件 Windows exe。

    python desktop/build_exe.py            # 生成 dist/OpenCrawlerLab.exe
    python desktop/build_exe.py --console # 调试用（保留控制台）

产物自带 Python 运行时与依赖，双击即可运行，不需要预装 Python。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = Path(__file__).with_name("launcher.py")
WEB = Path(__file__).parent / "web"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--console", action="store_true", help="保留控制台窗口")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("缺少 PyInstaller，请先执行: python -m pip install pyinstaller", file=sys.stderr)
        return 2

    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--console" if args.console else "--noconsole",
        "--name", "OpenCrawlerLab",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build" / "pyinstaller"),
        "--add-data", f"{WEB}{sep}desktop/web",
        "--collect-submodules", "opencrawler",
        "--hidden-import", "aiohttp", "--hidden-import", "bs4",
        "--hidden-import", "lxml", "--hidden-import", "yaml",
        "--hidden-import", "sqlite3", "--hidden-import", "asyncio",
        "--paths", str(ROOT / "src"),
        str(ENTRY),
    ]
    print("执行:", " ".join(cmd[:6]), "...")
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode:
        print("打包失败。可加 --console 重试查看日志。", file=sys.stderr)
        return proc.returncode
    exe = ROOT / "dist" / ("OpenCrawlerLab.exe" if sys.platform == "win32" else "OpenCrawlerLab")
    print(f"完成: {exe} ({exe.stat().st_size / 1024 / 1024:.1f} MiB)" if exe.exists() else "未找到产物")
    return 0 if exe.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
