"""一键把本项目开源到 GitHub（创建公开仓库 + 推送 main 分支）。

前置条件：环境变量 GITHUB_TOKEN 或 GH_TOKEN，需具备 repo 权限。

    export GITHUB_TOKEN=ghp_xxx          # Git Bash / Linux / macOS
    $env:GITHUB_TOKEN="ghp_xxx"          # PowerShell
    python scripts/publish_github.py --repo opencrawler-lab

两种推送通道
------------
* git  ：标准 `git push`（需要 github.com 可达），保留完整提交历史；
* api  ：通过 api.github.com 的 Git Data API 重放本地全部提交（需要 api.github.com 可达）。
         适用于 github.com 被代理/防火墙阻断的环境，同样保留完整提交历史与作者信息；
* auto ：默认，先探测 github.com，不可达则自动切到 api。

脚本不会把 Token 写进 .git/config，只在 push 时通过临时 http.extraheader 传递。
`--dry-run` 不需要 Token，只打印本地将要发布的提交与文件清单。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"
REPO_DESC = "通用、合规、异步高并发的网站爬虫学习框架"


# ---------------------------------------------------------------- HTTP
def api(method: str, path: str, token: str, payload: dict | None = None):
    """返回 (status, data)；HTTP 错误也作为结果返回，不抛异常。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "OpenCrawlerLab-Publisher/2.0",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw or "{}")
        except ValueError:
            body = {"message": raw[:400]}
        return exc.code, body
    except urllib.error.URLError as exc:
        return 0, {"message": f"网络错误: {exc.reason}"}


def github_reachable(timeout: float = 8.0) -> bool:
    """探测 github.com 是否可用于 git smart-http（代理常在此处返回 502）。"""
    try:
        req = urllib.request.Request("https://github.com", method="HEAD",
                                     headers={"User-Agent": "OpenCrawlerLab-Publisher/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:  # noqa: BLE001 - 任何失败都视为不可达，交给 API 通道
        return False


# ---------------------------------------------------------------- Git 本地读取
def git(*args: str, check: bool = True, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check,
        capture_output=True, text=not binary,
        encoding=None if binary else "utf-8", errors=None if binary else "replace",
    )


def local_commits() -> list[str]:
    """按时间正序返回本地 main 的全部提交。"""
    return git("log", "--reverse", "--format=%H", "main").stdout.split()


def tree_entries(commit: str) -> list[tuple[str, str, str]]:
    """读取某提交的 (mode, blob_sha, path) 列表。"""
    raw = git("ls-tree", "-r", "-z", commit, binary=True).stdout
    out = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        mode, obj_type, sha = meta.split()
        if obj_type != b"blob":
            continue
        out.append((mode.decode(), sha.decode(), path.decode("utf-8", "surrogateescape")))
    return out


def blob_content(sha: str) -> bytes:
    return git("cat-file", "-p", sha, binary=True).stdout


def commit_meta(sha: str) -> dict:
    fmt = "%an%x1f%ae%x1f%aI%x1f%cn%x1f%ce%x1f%cI%x1f%B"
    parts = git("show", "-s", f"--format={fmt}", sha).stdout.rstrip("\n").split("\x1f")
    return {
        "message": parts[6] if len(parts) > 6 else "Initial commit",
        "author": {"name": parts[0], "email": parts[1], "date": parts[2]},
        "committer": {"name": parts[3], "email": parts[4], "date": parts[5]},
    }


# ---------------------------------------------------------------- 通道 A：git push
def push_via_git(token: str, login: str, repo: str) -> int:
    remote_url = f"https://github.com/{login}/{repo}.git"
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", remote_url)
    push = subprocess.run(
        ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}",
         "push", "-u", "origin", "main"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if push.returncode:
        print(f"git push 失败: {push.stderr.strip()}", file=sys.stderr)
        return 6
    print(push.stderr.strip())
    return 0


# ---------------------------------------------------------------- 通道 B：Git Data API
def push_via_api(token: str, owner: str, repo: str) -> int:
    """用 Git Data API 重放本地提交历史，不依赖 github.com。"""
    base = f"/repos/{owner}/{repo}"
    commits = local_commits()
    if not commits:
        print("本地 main 没有提交，无法发布。", file=sys.stderr)
        return 7

    status, ref = api("GET", f"{base}/git/ref/heads/main", token)
    remote_head = ref.get("object", {}).get("sha") if status == 200 else None

    blob_cache: dict[str, str] = {}

    def upload_blobs(entries):
        tree = []
        for mode, sha, path in entries:
            if sha not in blob_cache:
                st, body = api("POST", f"{base}/git/blobs", token, {
                    "content": base64.b64encode(blob_content(sha)).decode("ascii"),
                    "encoding": "base64",
                })
                if st not in (200, 201) or "sha" not in body:
                    raise RuntimeError(f"上传 blob 失败 {path}: HTTP {st} {body.get('message')}")
                blob_cache[sha] = body["sha"]
            tree.append({"path": path, "mode": mode, "type": "blob", "sha": blob_cache[sha]})
        return tree

    def create_tree(entries):
        st, body = api("POST", f"{base}/git/trees", token, {"tree": upload_blobs(entries)})
        if st not in (200, 201) or "sha" not in body:
            raise RuntimeError(f"创建 tree 失败: HTTP {st} {body.get('message')}")
        return body["sha"]

    def create_commit(tree_sha, meta, parents):
        payload = {"message": meta["message"], "tree": tree_sha, "parents": parents,
                   "author": meta["author"], "committer": meta["committer"]}
        st, body = api("POST", f"{base}/git/commits", token, payload)
        if st not in (200, 201) or "sha" not in body:
            raise RuntimeError(f"创建 commit 失败: HTTP {st} {body.get('message')}")
        return body["sha"]

    try:
        if remote_head:
            # 远程仓库已有内容：以远程 HEAD 为父提交，追加一个与本地 HEAD 一致的提交
            tree_sha = create_tree(tree_entries(commits[-1]))
            new_head = create_commit(tree_sha, commit_meta(commits[-1]), [remote_head])
            st, body = api("PATCH", f"{base}/git/refs/heads/main", token,
                           {"sha": new_head, "force": False})
            if st not in (200, 201):
                raise RuntimeError(f"更新 main 引用失败: HTTP {st} {body.get('message')}")
            print(f"远程已有 main，追加 1 个提交；共 {len(tree_entries(commits[-1]))} 个文件")
        else:
            # 空仓库：逐个重放本地提交，保留完整历史与作者/日期
            parent = None
            for i, sha in enumerate(commits, 1):
                entries = tree_entries(sha)
                tree_sha = create_tree(entries)
                parents = [parent] if parent else []
                new_head = create_commit(tree_sha, commit_meta(sha), parents)
                parent = new_head
                print(f"  重放提交 {i}/{len(commits)}: {sha[:8]} · {len(entries)} 个文件")
            st, body = api("POST", f"{base}/git/refs", token,
                           {"ref": "refs/heads/main", "sha": parent})
            if st not in (200, 201):
                raise RuntimeError(f"创建 main 分支失败: HTTP {st} {body.get('message')}")
        api("PATCH", base, token, {"default_branch": "main"})
    except RuntimeError as exc:
        print(f"API 推送失败: {exc}", file=sys.stderr)
        return 8

    # 回读验证：远程树里的文件数应与本地 HEAD 一致
    st, tree = api("GET", f"{base}/git/trees/main?recursive=1", token)
    remote_files = sum(1 for e in tree.get("tree", []) if e.get("type") == "blob")
    local_files = len(tree_entries(commits[-1]))
    if st != 200 or remote_files != local_files:
        print(f"校验异常: 远程 {remote_files} 个文件 / 本地 {local_files} 个，HTTP {st}",
              file=sys.stderr)
        return 9
    print(f"远程校验通过：main 分支 {remote_files} 个文件，与本地一致")
    return 0


# ---------------------------------------------------------------- 主流程
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="创建 GitHub 公开仓库并推送本项目的 main 分支")
    parser.add_argument("--repo", default="opencrawler-lab", help="仓库名")
    parser.add_argument("--description", default=REPO_DESC)
    parser.add_argument("--mode", choices=("auto", "git", "api"), default="auto",
                        help="推送通道；auto 会在 github.com 不可达时切到 API")
    parser.add_argument("--no-commit", action="store_true", help="不自动创建提交")
    parser.add_argument("--dry-run", action="store_true", help="不联网、不需要 Token，只列发布计划")
    args = parser.parse_args(argv)

    commits = local_commits()
    head_files = tree_entries(commits[-1]) if commits else []
    if args.dry_run:
        print(f"发布计划（不联网、不改动工作区）\n  仓库名    : {args.repo}")
        print(f"  本地提交  : {len(commits)} 个\n  HEAD 文件 : {len(head_files)} 个")
        print(f"  github.com: {'可达' if github_reachable() else '不可达 → 将走 API 通道'}")
        for sha in commits:
            print(f"    {sha[:8]}  {commit_meta(sha)['message'].splitlines()[0]}")
        return 0

    if not (ROOT / ".git").exists():
        git("init", "-b", "main")
    if not args.no_commit:
        git("add", "-A")
        commit = git("commit", "-m", "chore: add API-based publishing channel", check=False)
        if commit.returncode and "nothing to commit" not in (commit.stdout + commit.stderr).lower():
            print(commit.stdout + commit.stderr, file=sys.stderr)
            return 5
    git("branch", "-M", "main")

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("未检测到 GITHUB_TOKEN / GH_TOKEN，无法代替你完成 GitHub 登录授权。", file=sys.stderr)
        print("准备好具备 repo 权限的 Token 后设置环境变量并重新运行本脚本：", file=sys.stderr)
        print("  Git Bash : export GITHUB_TOKEN=ghp_xxx && python scripts/publish_github.py", file=sys.stderr)
        print("  PowerShell: $env:GITHUB_TOKEN='ghp_xxx'; python scripts/publish_github.py", file=sys.stderr)
        print("本地仓库已准备就绪，授权后无需再做任何改动即可一键推送。", file=sys.stderr)
        return 2

    st, user = api("GET", "/user", token)
    if st != 200 or "login" not in user:
        print(f"GitHub 认证失败: HTTP {st} {user.get('message')}", file=sys.stderr)
        return 3
    login = user["login"]
    print(f"已认证为 GitHub 用户: {login}")

    st, repo = api("POST", "/user/repos", token, {
        "name": args.repo,
        "description": args.description,
        "homepage": f"https://github.com/{login}/{args.repo}",
        "private": False,
        "has_issues": True,
        "has_projects": False,
        "has_wiki": False,
        "license_template": "mit",
    })
    if st in (200, 201):
        html_url = repo["html_url"]
        print(f"已创建公开仓库: {html_url}")
    elif st == 422:
        html_url = f"https://github.com/{login}/{args.repo}"
        print(f"仓库已存在，使用: {html_url}")
    else:
        print(f"创建仓库失败: HTTP {st} {repo.get('message')}", file=sys.stderr)
        return 4

    mode = args.mode
    if mode == "auto":
        mode = "git" if github_reachable() else "api"
        print(f"推送通道: {mode}" + ("（github.com 不可达，已自动切换）" if mode == "api" else ""))
    if mode == "git":
        rc = push_via_git(token, login, args.repo)
        if rc and github_reachable() is False:
            print("git 通道失败，尝试 API 通道重放提交历史…", file=sys.stderr)
            rc = push_via_api(token, login, args.repo)
    else:
        rc = push_via_api(token, login, args.repo)
    if rc:
        return rc

    # 本地 remote 始终指向真实仓库（即使当前网络下 git fetch 不通）
    remote_url = f"https://github.com/{login}/{args.repo}.git"
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", remote_url)
    print(f"\n开源完成: {html_url}")
    print(f"Actions: {html_url}/actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
