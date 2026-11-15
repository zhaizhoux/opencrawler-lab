# 发布到 GitHub

本地仓库已经 `git init`、完成首次提交、配置好 `origin`，并把 `.gitignore`、
MIT 许可、CI、Issue 模板等开源配套全部准备妥当。**剩下的唯一一步是身份授权**：
创建远程仓库与推送需要 GitHub 账号凭证，自动化脚本不能替你登录。

## 方式一：Token + 一键脚本（推荐）

1. 在 GitHub → Settings → Developer settings → Personal access tokens 生成一个
   具备 `repo` 权限的 Token。
2. 设置环境变量并运行：

```bash
# Git Bash / Linux / macOS
export GITHUB_TOKEN=ghp_xxx
python scripts/publish_github.py --repo opencrawler-lab

# PowerShell
$env:GITHUB_TOKEN = "ghp_xxx"
python scripts/publish_github.py --repo opencrawler-lab
```

脚本会：验证身份 → 创建公开仓库（已存在则复用）→ 选择推送通道 → 推送 `main` →
回读远程树校验文件数。Token 只通过临时的 `http.extraheader` 或 API 请求头传递，
**不会写入 `.git/config`，也不会落盘**。

### 两条推送通道

| 通道 | 依赖 | 说明 |
| --- | --- | --- |
| `git` | `github.com` 可达 | 标准 `git push -u origin main` |
| `api` | `api.github.com` 可达 | 用 Git Data API 逐个重放本地提交（blob → tree → commit → ref），保留完整提交历史、作者与日期；远程仓库非空时追加一个等价提交 |

默认 `--mode auto`：先探测 `github.com`，被代理/防火墙阻断就自动切到 `api`。
可显式指定 `--mode git` / `--mode api`。`--dry-run` 不联网、不需要 Token，
会列出将发布的提交数、文件数以及当前网络下会选哪条通道。

```bash
python scripts/publish_github.py --dry-run
python scripts/publish_github.py --repo opencrawler-lab --mode api
```

## 方式二：使用 GitHub 连接器

在 WorkBuddy 的连接器管理里启用 GitHub 并完成授权，然后让助手把当前仓库推送到
你自己的账号下（脚本会自动换成你的 `login`）。

## 方式三：手动导入（无需命令行）

仓库根目录旁已生成 `opencrawler-lab.zip`（由 `git archive` 导出的纯净源码，
不含 `.git`、缓存与抓取数据）。在 GitHub 新建仓库后上传/导入该压缩包即可。

## 推送前自检清单

- [ ] `python -m pytest tests -q` 全绿
- [ ] `python -m opencrawler selftest` 输出 `PASS`
- [ ] `ruff check src tests scripts examples` 无错误
- [ ] `user_agent` 已改成能联系到你的标识
- [ ] 仓库中没有 `output/`、`*.sqlite3`、`*.jsonl` 或任何真实抓取数据
- [ ] 已阅读 [ETHICS.md](ETHICS.md)

## 当前状态（2026-11-15 复核）

- **凭证**：无 `GITHUB_TOKEN` / `GH_TOKEN` 环境变量，无 GitHub CLI，无 `~/.git-credentials`；
  Git 凭据管理器中确实存有 `github.com` 的用户名与密码（用户名 `zhaizhoux`），
  但它只能被 `git push` 使用，无法用于 API 通道。会话中的 GitHub 连接器授权尚未完成。
- **网络**：`api.github.com` 直连与代理均返回 200；`github.com` 走代理返回
  `CONNECT tunnel failed, response 502`、直连超时，标准 `git push` 因此失败
  （`fatal: unable to access ...: CONNECT tunnel failed, response 502`）。
  无 SSH 密钥，`ssh.github.com:443` 亦不可达。
- **已就绪**：发布脚本 v2 支持 `--mode api`，可在只有 `api.github.com` 可达的环境下
  通过 Git Data API 重放本地 2 个提交 / 44 个文件，并回读校验。`--dry-run` 已通过，
  `ruff check` 通过。
- **还差一步**：完成一次身份授权（连接器点选授权，或设置一个具备 `repo` 权限的
  `GITHUB_TOKEN`）。授权到位后运行一条命令即可完成发布，不需要改动仓库内容。

在此之前**没有创建任何远程仓库，也没有伪造发布结果**。
