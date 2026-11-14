"""一键把本项目开源到 GitHub（创建公开仓库 + 推送 main 分支）。

前置条件：环境变量 GITHUB_TOKEN 或 GH_TOKEN，需具备 repo 权限。

    export GITHUB_TOKEN=ghp_xxx          # Git Bash / Linux / macOS
    $env:GITHUB_TOKEN="ghp_xxx"          # PowerShell
    python scripts/publish_github.py --repo opencrawler-lab

脚本不会把 Token 写进 .git/config，只在 push 时通过临时 http.extraheader 传递。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"


def api_request(method: str, path: str, token: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "OpenCrawlerLab-Publisher/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8") or "{}")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="创建 GitHub 公开仓库并推送本项目的 main 分支")
    parser.add_argument("--repo", default="opencrawler-lab", help="仓库名")
    parser.add_argument("--description", default="通用、合规、异步高并发的网站爬虫学习框架")
    parser.add_argument("--no-commit", action="store_true", help="不自动创建提交（假定已提交）")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("未检测到 GITHUB_TOKEN / GH_TOKEN，无法代替你完成 GitHub 登录授权。", file=sys.stderr)
        print("准备好具备 repo 权限的 Token 后设置环境变量并重新运行本脚本：", file=sys.stderr)
        print("  Git Bash : export GITHUB_TOKEN=ghp_xxx && python scripts/publish_github.py", file=sys.stderr)
        print("  PowerShell: $env:GITHUB_TOKEN='ghp_xxx'; python scripts/publish_github.py", file=sys.stderr)
        print("本地仓库已准备就绪，授权后无需再做任何改动即可一键推送。", file=sys.stderr)
        return 2

    try:
        _, user = api_request("GET", "/user", token)
        login = user["login"]
        print(f"已认证为 GitHub 用户: {login}")
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        print(f"GitHub 认证失败: {exc}", file=sys.stderr)
        return 3

    status = 0
    try:
        status, repo = api_request("POST", "/user/repos", token, {
            "name": args.repo,
            "description": args.description,
            "homepage": "https://github.com/OpenCrawlerLab/opencrawler-lab",
            "private": False,
            "has_issues": True,
            "has_projects": False,
            "has_wiki": False,
            "license_template": "mit",
        })
        print(f"已创建公开仓库: {repo['html_url']}")
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            repo = {"html_url": f"https://github.com/{login}/{args.repo}"}
            print(f"仓库已存在，使用: {repo['html_url']}")
        else:
            print(f"创建仓库失败: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')}", file=sys.stderr)
            return 4

    if not (ROOT / ".git").exists():
        git("init", "-b", "main")
    if not args.no_commit:
        git("add", "-A")
        commit = git("commit", "-m", "feat: initial release of OpenCrawlerLab 0.1.0", check=False)
        if commit.returncode and "nothing to commit" not in (commit.stdout + commit.stderr).lower():
            print(commit.stdout + commit.stderr, file=sys.stderr)
            return 5
    git("branch", "-M", "main")
    remote_url = f"https://github.com/{login}/{args.repo}.git"
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", remote_url)
    push = subprocess.run(
        ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}", "push", "-u", "origin", "main"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if push.returncode:
        print(f"推送失败: {push.stderr}", file=sys.stderr)
        return 6
    print(push.stderr.strip())
    print(f"\n开源完成: {repo['html_url']}")
    print(f"Actions: {repo['html_url']}/actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
