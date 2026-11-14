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

脚本会：验证身份 → 创建公开仓库（已存在则复用）→ 添加 remote → 推送 `main`。
Token 只通过临时的 `http.extraheader` 传递，**不会写入 `.git/config`**。

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

## 当前状态

最后一次自动化尝试的结果：本机**没有** `GITHUB_TOKEN` / `GH_TOKEN`，
也未安装 GitHub CLI 或已保存的 Git 凭证，因此脚本按预期以退出码 2 结束，
没有创建任何远程仓库，也没有伪造发布结果。授权后重跑脚本即可完成开源发布。
