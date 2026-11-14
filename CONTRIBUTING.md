# 贡献指南

欢迎把框架改得更好用、**更礼貌**。本项目定位是教学软件，因此"可读性 > 炫技"。

## 开发流程

```bash
git clone <your-fork>
cd opencrawler-lab
python -m venv .venv && . .venv/bin/activate
pip install -e ".[full,dev]"
python -m pytest tests -q
python -m opencrawler selftest
ruff check src tests
```

提交前请确保：

- 新增行为有对应测试（尤其是合规相关行为，必须有回归测试）；
- 默认值不会被改得更激进（更高并发、更短间隔、关闭 robots）；
- 不引入任何绕过访问控制、验证码、反爬机制的能力；
- 文档同步更新（README / ETHICS / ARCHITECTURE 视情况而定）；
- 提交信息用简短的祈使句，例如 `fix: keep port when fetching robots.txt`。

## 代码约定

- Python 3.10+，类型标注使用 `from __future__ import annotations`；
- 行宽 110，ruff 规则见 `pyproject.toml`；
- 第三方依赖尽量可选，缺失时要有降级路径（参考 `extractor.py`）；
- 单个任务异常必须被隔离，不能让整个引擎退出；
- 网络请求必须经过 `RobotsPolicy` 与 `DomainLimiter`。

## 报告问题

请附：Python 版本、操作系统、最小复现配置、相关日志（`--log-level DEBUG`）。
**不要**在 Issue 里贴真实站点的敏感 URL、Cookie 或抓取到的个人数据。

## 行为准则

保持友善、就事论事。任何用于滥用爬虫的 PR 都会被关闭。
