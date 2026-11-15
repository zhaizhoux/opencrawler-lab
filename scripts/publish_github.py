"""把本项目开源到 GitHub：创建/复用公开仓库并推送 main 分支。

Token 来源（按优先级，均不会写进仓库）
--------------------------------------
1. ``--token-file`` 指定文件
2. 环境变量 ``GITHUB_TOKEN`` / ``GH_TOKEN`` / ``GITHUB_PAT`` / ``GH_PAT``
3. 用户配置 ``~/.config/opencrawler-lab/token``（权限 0600）
4. 项目根目录 ``.env`` 的 ``GITHUB_TOKEN=...``（已被 .gitignore 排除）
5. ``--value``（会留在 shell 历史，不推荐）
6. ``--use-git-credential``：由 Git 凭据管理器提供，桌面授权弹窗由本人确认

Token 权限说明
--------------
* classic PAT（``ghp_``）：勾选 ``repo``，可建仓 + 推送，全自动完成。
* fine-grained PAT（``github_pat_``）：可读写已授权仓库，但 GitHub 通常拒绝它
  调用 ``POST /user/repos`` 建仓（403 Resource not accessible）。此时请先在
  https://github.com/new 手动创建一个**空的公开仓库**，再用 ``--skip-create`` 推送；
  或在 Token 设置里把 Repository access 改为 All repositories 并补
  ``Administration: read/write``。

命令
----
    python scripts/publish_github.py --check-token       # 只验证身份与权限
    python scripts/publish_github.py --dry-run           # 不联网，列发布计划
    python scripts/publish_github.py                     # 自动建仓并推送
    python scripts/publish_github.py --skip-create       # 仓库已存在，直接推送
    python scripts/publish_github.py --mode api          # 强制走 Git Data API

推送通道
--------
* ``git``  ：标准 ``git push``（需要 github.com 可达）
* ``api``  ：通过 api.github.com 的 Git Data API 重放本地提交（github.com 被阻断时可用）
* ``auto`` ：默认，自动选择

``GITHUB_API_URL`` 可覆盖 API 基址，用于本地演练或 GitHub Enterprise。
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
API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
TOKEN_FILE = Path.home() / ".config" / "opencrawler-lab" / "token"
ENV_VARS = ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT", "GH_PAT")
REPO_DESC = "通用、合规、异步高并发的网站爬虫学习框架"


# ---------------------------------------------------------------- HTTP
def api_raw(method: str, path: str, token: str, payload: dict | None = None):
    """返回 (status, body, headers)；HTTP 错误也作为结果返回，不抛异常。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "OpenCrawlerLab-Publisher/3.0",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            try:
                body = json.loads(raw)
            except ValueError:
                body = {}
            return resp.status, body, dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw or "{}")
        except ValueError:
            body = {"message": raw[:400]}
        return exc.code, body, dict(exc.headers.items()) if exc.headers else {}
    except urllib.error.URLError as exc:
        return 0, {"message": f"网络错误: {exc.reason}"}, {}


def api(method: str, path: str, token: str, payload: dict | None = None):
    status, body, _ = api_raw(method, path, token, payload)
    return status, body


def github_reachable(timeout: float = 8.0) -> bool:
    """探测 github.com 是否可用于 git smart-http（代理常在此处返回 502）。"""
    try:
        req = urllib.request.Request("https://github.com", method="HEAD",
                                     headers={"User-Agent": "OpenCrawlerLab-Publisher/3.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:  # noqa: BLE001 - 任何失败都视为不可达，交给 API 通道
        return False


# ---------------------------------------------------------------- 凭证
def credential_from_git() -> tuple[str | None, str]:
    """由 Git 凭据管理器提供 github.com 凭证；桌面弹窗由账号本人确认。

    凭证只保存在内存中用于请求头，不打印、不写日志、不落盘到仓库。
    """
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            cwd=ROOT, capture_output=True, text=True, env=env, timeout=90,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"调用 git 凭据管理器失败（{type(exc).__name__}）"
    fields = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    value = fields.get("password") or fields.get("token")
    if not value:
        return None, "Git 凭据管理器未返回凭证（可能取消了授权窗口）"
    return value, "Git 凭据管理器 · github.com（弹窗由本人确认）"


def resolve_token(args) -> tuple[str | None, str]:
    """返回 (token, 来源描述)；描述中绝不包含 token 本身。"""
    token_file = getattr(args, "token_file", None)
    if token_file:
        path = Path(token_file).expanduser()
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value, f"文件 {path}"
        return None, f"指定的凭证文件不存在: {path}"

    for key in ENV_VARS:
        value = os.environ.get(key, "").strip()
        if value:
            return value, f"环境变量 {key}"

    if TOKEN_FILE.is_file():
        value = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value, f"用户配置 {TOKEN_FILE}"

    dotenv = ROOT / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GITHUB_TOKEN="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value, f"项目 .env（{dotenv}）"

    value = getattr(args, "value", None)
    if value and value.strip():
        return value.strip(), "命令行 --value"

    if getattr(args, "use_git_credential", False):
        value, how = credential_from_git()
        if value:
            return value, how
        return None, how

    return None, "未设置"


def verify_token(token: str) -> tuple[dict | None, str]:
    """验证身份，并判断 Token 类型与权限范围。"""
    status, body, headers = api_raw("GET", "/user", token)
    if status != 200 or "login" not in body:
        return None, f"GitHub 认证失败: HTTP {status} {body.get('message', '')}"
    scopes = [s.strip() for s in headers.get("X-OAuth-Scopes", "").split(",") if s.strip()]
    if scopes:
        kind = "classic PAT / OAuth token"
        has_repo = "repo" in scopes or "public_repo" in scopes
    else:
        kind = "fine-grained PAT（无 scopes 响应头，实际权限以服务端为准）"
        has_repo = True
    return {"login": body["login"], "scopes": scopes, "kind": kind,
            "has_repo": has_repo, "fine_grained": not scopes}, ""


# ---------------------------------------------------------------- Git 本地读取
def git(*args: str, check: bool = True, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check,
        capture_output=True, text=not binary,
        encoding=None if binary else "utf-8", errors=None if binary else "replace",
    )


def local_commits() -> list[str]:
    """按时间正序返回当前 HEAD 的全部提交。"""
    return git("log", "--reverse", "--format=%H", "HEAD").stdout.split()


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
    # GitHub git smart-http 只接受 Basic（用户名固定为 x-access-token），不接受 bearer
    basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    push = subprocess.run(
        ["git", "-c", f"http.extraheader=AUTHORIZATION: basic {basic}",
         "push", "-u", "origin", "main"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if push.returncode:
        print(f"git push 失败: {push.stderr.strip()}", file=sys.stderr)
        return 6
    print(push.stderr.strip())
    return 0


# ---------------------------------------------------------------- 通道 B：Git Data API
def ensure_repository_initialized(base: str, token: str) -> str:
    """空仓库的 Git Data API 全部返回 409，先用 Contents API 建一个初始提交。"""
    readme = (ROOT / "README.md").read_bytes()
    st, body = api("PUT", f"{base}/contents/README.md", token, {
        "message": "Initialize repository",
        "content": base64.b64encode(readme).decode("ascii"),
    })
    if st not in (200, 201) or not isinstance(body.get("commit"), dict):
        raise RuntimeError(f"初始化空仓库失败: HTTP {st} {body.get('message')}")
    return body["commit"]["sha"]


def push_via_api(token: str, owner: str, repo: str) -> int:
    """用 Git Data API 重放本地提交历史，不依赖 github.com。"""
    base = f"/repos/{owner}/{repo}"
    commits = local_commits()
    if not commits:
        print("本地 HEAD 没有提交，无法发布。", file=sys.stderr)
        return 7

    status, ref = api("GET", f"{base}/git/ref/heads/main", token)
    message = str(ref.get("message", ""))
    empty_repo = status == 409 or (status != 200 and "empty" in message.lower())
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
            entries = tree_entries(commits[-1])
            tree_sha = create_tree(entries)
            new_head = create_commit(tree_sha, commit_meta(commits[-1]), [remote_head])
            st, body = api("PATCH", f"{base}/git/refs/heads/main", token,
                           {"sha": new_head, "force": False})
            if st not in (200, 201):
                raise RuntimeError(f"更新 main 引用失败: HTTP {st} {body.get('message')}")
            print(f"远程已有 main，追加 1 个提交；共 {len(entries)} 个文件")
        else:
            parent = None
            if empty_repo:
                parent = ensure_repository_initialized(base, token)
                print("空仓库已用 Contents API 建立初始提交，随后线性重放本地历史")
            for i, sha in enumerate(commits, 1):
                entries = tree_entries(sha)
                tree_sha = create_tree(entries)
                parents = [parent] if parent else []
                new_head = create_commit(tree_sha, commit_meta(sha), parents)
                parent = new_head
                print(f"  重放提交 {i}/{len(commits)}: {sha[:8]} · {len(entries)} 个文件")
            if empty_repo:
                st, body = api("PATCH", f"{base}/git/refs/heads/main", token,
                               {"sha": parent, "force": False})
            else:
                st, body = api("POST", f"{base}/git/refs", token,
                               {"ref": "refs/heads/main", "sha": parent})
            if st not in (200, 201):
                raise RuntimeError(f"写入 main 引用失败: HTTP {st} {body.get('message')}")
        api("PATCH", base, token, {"default_branch": "main"})
    except RuntimeError as exc:
        print(f"API 推送失败: {exc}", file=sys.stderr)
        return 8

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
    parser.add_argument("--skip-create", action="store_true",
                        help="仓库已存在，跳过建仓（fine-grained PAT 必用）")
    parser.add_argument("--check-token", action="store_true", help="只验证身份与权限后退出")
    parser.add_argument("--token-file", help="从指定文件读取 Token")
    parser.add_argument("--value", help="直接给出 Token（会留在 shell 历史，不推荐）")
    parser.add_argument("--use-git-credential", action="store_true",
                        help="从 Git 凭据管理器读取凭证，桌面弹窗由本人确认")
    args = parser.parse_args(argv)

    token, source = resolve_token(args)
    if args.check_token:
        if not token:
            print(f"未检测到 Token（{source}）。", file=sys.stderr)
            return 2
        info, err = verify_token(token)
        if err:
            print(err, file=sys.stderr)
            return 3
        print(f"来源    : {source}")
        print(f"身份    : {info['login']}")
        print(f"类型    : {info['kind']}")
        print(f"scopes  : {', '.join(info['scopes']) or '(无)'}")
        print(f"repo 权限: {'是' if info['has_repo'] else '否'}")
        if info["fine_grained"]:
            print("提示    : fine-grained PAT 无法建仓时，请手动建空仓库后用 --skip-create 推送。")
        return 0

    commits = local_commits()
    head_files = tree_entries(commits[-1]) if commits else []
    if args.dry_run:
        print(f"发布计划（不联网、不改动工作区）\n  仓库名    : {args.repo}")
        print(f"  本地提交  : {len(commits)} 个\n  HEAD 文件 : {len(head_files)} 个")
        print(f"  凭证状态  : {'已就绪（' + source + '）' if token else '未设置（' + source + '）'}")
        print(f"  github.com: {'可达' if github_reachable() else '不可达 → 将走 API 通道'}")
        for sha in commits:
            print(f"    {sha[:8]}  {commit_meta(sha)['message'].splitlines()[0]}")
        return 0

    if not (ROOT / ".git").exists():
        git("init", "-b", "main")
    if not args.no_commit:
        git("add", "-A")
        commit = git("commit", "-m", "chore: prepare GitHub publishing", check=False)
        if commit.returncode and "nothing to commit" not in (commit.stdout + commit.stderr).lower():
            print(commit.stdout + commit.stderr, file=sys.stderr)
            return 5
    git("branch", "-M", "main")

    if not token:
        print(f"未检测到 Token（{source}），无法完成 GitHub 身份认证。", file=sys.stderr)
        print("请设置环境变量 GITHUB_TOKEN，或把 Token 写入 "
              f"{TOKEN_FILE}（仓库之外，不会被提交）。", file=sys.stderr)
        return 2
    print(f"凭证来源: {source}（不回显）")

    info, err = verify_token(token)
    if err:
        print(err, file=sys.stderr)
        return 3
    login = info["login"]
    print(f"已认证为 GitHub 用户: {login} · {info['kind']}")
    if info["scopes"]:
        print(f"Token scopes: {', '.join(info['scopes'])}")
    if not info["has_repo"]:
        print("警告: Token 未见 repo 权限，推送可能失败。classic PAT 请勾选 repo。")

    html_url = f"https://github.com/{login}/{args.repo}"
    base = f"/repos/{login}/{args.repo}"
    if args.skip_create:
        st, existing = api("GET", base, token)
        if st != 200:
            print(f"仓库 {html_url} 不可访问: HTTP {st} {existing.get('message')}", file=sys.stderr)
            print("若刚在网页创建，请确认仓库名一致；fine-grained PAT 还需把该仓库加入授权范围。",
                  file=sys.stderr)
            return 4
        permissions = existing.get("permissions", {})
        print(f"复用已有仓库: {html_url} · push={permissions.get('push')} "
              f"admin={permissions.get('admin')}")
    else:
        st, repo, headers = api_raw("POST", "/user/repos", token, {
            "name": args.repo,
            "description": args.description,
            "homepage": html_url,
            "private": False,
            "has_issues": True,
            "has_projects": False,
            "has_wiki": False,
            "auto_init": False,
        })
        if st in (200, 201):
            html_url = repo.get("html_url", html_url)
            print(f"已创建公开仓库: {html_url}")
        elif st == 422:
            print(f"仓库已存在，使用: {html_url}")
        elif st == 403 and info["fine_grained"]:
            print(f"建仓被拒绝: HTTP 403 {repo.get('message')}", file=sys.stderr)
            print("fine-grained PAT 通常无权调用 POST /user/repos。两种解法：", file=sys.stderr)
            print("  1) 在 https://github.com/new 创建空的公开仓库 opencrawler-lab，"
                  "然后运行： python scripts/publish_github.py --skip-create", file=sys.stderr)
            print("  2) 换用勾选了 repo 的 classic PAT（ghp_），即可全自动建仓 + 推送。",
                  file=sys.stderr)
            needed = headers.get("X-Accepted-GitHub-Permissions")
            if needed:
                print(f"服务端要求权限: {needed}", file=sys.stderr)
            return 4
        else:
            print(f"创建仓库失败: HTTP {st} {repo.get('message')}", file=sys.stderr)
            return 4

    mode = args.mode
    if mode == "auto":
        mode = "git" if github_reachable() else "api"
        print(f"推送通道: {mode}" + ("（github.com 不可达，已自动切换）" if mode == "api" else ""))
    if mode == "git":
        rc = push_via_git(token, login, args.repo)
        if rc:
            print("git 通道失败，改用 API 通道重放提交历史…", file=sys.stderr)
            rc = push_via_api(token, login, args.repo)
    else:
        rc = push_via_api(token, login, args.repo)
    if rc:
        return rc

    remote_url = f"https://github.com/{login}/{args.repo}.git"
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", remote_url)
    print(f"\n开源完成: {html_url}")
    print(f"Actions: {html_url}/actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
