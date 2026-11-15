# 发布到 GitHub

## 当前状态：已发布 ✅

| 项目 | 结果 |
| --- | --- |
| 仓库 | **https://github.com/zhaizhoux/opencrawler-lab**（Public） |
| 默认分支 | `main` |
| 提交历史 | 完整重放本地 `HEAD` 历史，保留作者与日期 |
| 文件 | 60 个，与本地 `HEAD` 完全一致 |
| 校验 | `GET /git/trees/main?recursive=1` 回读 60 个文件；关键文件齐全；无凭证或抓取数据泄露 |
| Actions | https://github.com/zhaizhoux/opencrawler-lab/actions |

三个仓库的源码归档 `opencrawler-lab.zip` / `opencrawler-java.zip` / `opencrawler-cpp.zip`
（仓库上一级目录）均由 `git archive` 生成，不含 `.git`，可随时用于手动导入。

| 仓库 | 独立回读（GitHub API） | CI |
| --- | --- | --- |
| opencrawler-lab | Public / `main` / 60 文件 / 无可疑文件 | success |
| opencrawler-java | Public / `main` / 34 文件 / 无可疑文件 | success |
| opencrawler-cpp | Public / `main` / 27 文件 / 无可疑文件 | success |

回读使用 `GET /repos/{owner}/{repo}`、`GET /git/trees/main?recursive=1`、
`GET /commits`、`GET /actions/runs`，不依赖本地缓存。

---

## 凭证怎么设置

Token 属于账号凭证，**绝不写入仓库**。脚本按以下优先级读取（只描述来源，不回显值）：

1. `--token-file <path>`
2. 环境变量 `GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_PAT` / `GH_PAT`
3. 用户配置 `~/.config/opencrawler-lab/token`（推荐，仓库之外，权限设为 0600）
4. 项目根目录 `.env` 中的 `GITHUB_TOKEN=...`（已由 `.gitignore` 排除）
5. `--value`（会留在 shell 历史，不推荐）
6. `--use-git-credential`（由 Git 凭据管理器提供；若弹出授权窗口，需账号本人在桌面确认）

```bash
# 写入 token 文件（Git Bash）
mkdir -p ~/.config/opencrawler-lab
printf '%s\n' 'ghp_xxx' > ~/.config/opencrawler-lab/token
chmod 600 ~/.config/opencrawler-lab/token

# 或临时用环境变量
export GITHUB_TOKEN=ghp_xxx
```

### 需要什么权限

| Token 类型 | 前缀 | 能否建仓 | 权限要求 |
| --- | --- | --- | --- |
| classic PAT（推荐） | `ghp_` | 可以 | 勾选 `repo`（要跑 CI 再勾 `workflow`） |
| OAuth App token | `gho_` | 可以 | scopes 含 `repo` |
| fine-grained PAT | `github_pat_` | **通常不行** | `Contents: read/write` + `Metadata: read`；建仓还需 `Administration: read/write` 且 Repository access 为 All repositories |

先检查再发布：

```bash
python scripts/publish_github.py --check-token
```

## 发布命令速查

```bash
python scripts/publish_github.py --dry-run        # 不联网，列提交数/文件数/通道/凭证状态
python scripts/publish_github.py                  # 自动建仓 + 推送（auto 选通道）
python scripts/publish_github.py --mode api       # 强制 Git Data API 通道
python scripts/publish_github.py --skip-create    # 仓库已存在，跳过建仓直接推送
python scripts/publish_github.py --no-commit      # 不自动 git add/commit
```

脚本流程：验证身份与权限 → 创建公开仓库（已存在则复用）→ 选择通道 → 推送 →
回读远程树校验文件数。Token 只放在请求头里，不写进 `.git/config`。

### 两条推送通道

| 通道 | 依赖 | 说明 |
| --- | --- | --- |
| `git` | `github.com` 可达 | `git push -u origin main`，用 Basic 认证（`x-access-token`） |
| `api` | `api.github.com` 可达 | Git Data API 重放 blob → tree → commit → ref，保留完整历史、作者与日期 |

`--mode auto` 先探测 `github.com`，不可达就切 `api`；`git` 通道失败也会自动切 `api`。
`GITHUB_API_URL` 可覆盖 API 基址（用于本地演练或 GitHub Enterprise）。

### 其他方式

- **GitHub 连接器**：在 WorkBuddy 连接器管理里启用 GitHub 并授权，让助手直接推送。
- **手动导入**：把 `opencrawler-lab.zip` 上传到 GitHub 新建的仓库，无需命令行。

---

## 一个脚本发布三个独立仓库（0.2.0 起）

`--root` 让本脚本服务于任意本地仓库：它读取该目录的 Git 历史、README（用于空仓库初始化）
与文件树，再用 API 通道重放，彼此完全独立。

| 仓库 | 本地目录 | 语言 / 并发模型 |
| --- | --- | --- |
| [opencrawler-lab](https://github.com/zhaizhoux/opencrawler-lab) | 本仓库 | Python · asyncio |
| [opencrawler-java](https://github.com/zhaizhoux/opencrawler-java) | `../opencrawler-java` | Java 21 · 虚拟线程 |
| [opencrawler-cpp](https://github.com/zhaizhoux/opencrawler-cpp) | `../opencrawler-cpp` | C++20 · 线程池 |

```bash
# 新建仓库（自动建仓 + 初始化 + 重放全部提交）
python scripts/publish_github.py --root ../opencrawler-java --repo opencrawler-java \
  --description "零依赖、合规、高并发的 Java 21 虚拟线程爬虫学习框架" --mode api --no-commit
python scripts/publish_github.py --root ../opencrawler-cpp --repo opencrawler-cpp \
  --description "零第三方依赖、合规、高并发的 C++20 爬虫学习框架" --mode api --no-commit

# 已有仓库追加本地新提交
python scripts/publish_github.py --skip-create --mode api --no-commit
```

`--dry-run` 现在对尚未 `git init` 的目录也会安全返回计划（0 个提交），不会抛异常。

## 排障记录（本次发布真实遇到并已修复）

1. **`github.com` 被代理阻断**：`CONNECT tunnel failed, 502`，直连超时，而
   `api.github.com` 正常。→ 新增 API 通道，用 Git Data API 重放提交历史，绕开该域名。
2. **fine-grained PAT 建仓 403**：`Resource not accessible by personal access token`。
   它对已有仓库有 `push/admin`，但无权调用 `POST /user/repos`。→ 改用 classic PAT，
   或手动在 https://github.com/new 建空仓库后用 `--skip-create` 推送；脚本在 403 时
   会输出这两条具体解法。
3. **空仓库 Git Data API 全部 409**：`Git Repository is empty`，连 `POST /git/trees`
   带内联 content 也一样。→ 先用 Contents API `PUT /contents/README.md` 建立初始提交，
   再线性重放全部本地提交并快进 `main` 引用。
4. **`git push` 报 `invalid credentials`**：`AUTHORIZATION: bearer <token>` 不被 GitHub
   git smart-http 接受。→ 改为 Basic：`base64("x-access-token:<token>")`。

## 推送前自检清单

- [ ] `python -m pytest tests -q` 全绿
- [ ] `python -m opencrawler selftest` 输出 `PASS`
- [ ] `ruff check src tests scripts examples` 无错误
- [ ] `user_agent` 已改成能联系到你的标识
- [ ] 仓库中没有 `output/`、`*.sqlite3`、`*.jsonl` 或任何真实抓取数据
- [ ] 仓库中没有 `.env`、`*.token` 或任何 Token 明文
- [ ] 已阅读 [ETHICS.md](ETHICS.md)

## 安全提醒

Token 一旦在聊天、终端历史或日志里以明文出现过，就应视为已泄露：
发布完成后请到 GitHub → Settings → Developer settings → Personal access tokens
**立即吊销并重新生成**，本地 `~/.config/opencrawler-lab/token` 同步删除或替换。
