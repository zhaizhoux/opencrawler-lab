# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [0.3.0] - 2026-11-15

桌面控制台与接口契约的一次统一完善，三仓库同步发布。

### 新增
- `/api/info`：返回 `implementation` / `language` / `version` / `platform` /
  `started_at` / `uptime_seconds` / `endpoints` / `compliance_defaults` /
  `storage_backends` / `result_scan_limit`
- `status` 增加 `implementation` / `platform` / `uptime_seconds`，空闲态补齐全部数值字段
- `/api/results` 支持 `q`（URL/标题子串）、`kind`（精确类型）、`offset`（向历史翻页），
  返回 `{items, total, limit, offset}`；扫描窗口上限 20000 行
- 共用前端 v0.3：12 指标 + 吞吐趋势、结果搜索/筛选/详情/CSV、日志过滤与暂停、
  配置预设、深浅主题、SSE 状态与轮询兜底、键盘快捷键、服务端配置保存
- 三语言自测新增 `/api/info`、结果筛选、状态字段、Content-Type 等断言

### 修复
- Python 一键启动器原按「启动器在项目根目录」的假设查找
  `desktop/launcher.py` 与同目录 `OpenCrawlerLab.exe`，实际交付中启动器在
  `desktop/`、打包程序在 `dist/`，双击会直接弹错误框
- 三个启动器统一为路径自适应 + 额外参数转发（`--no-browser --port N`）+ 无黑框启动；
  实测三语言一键启动均返回 `0.3.0` 与新前端

- Java `asset()` 漏设 `Content-Type` 且缺文件时仍返回 200
- C++ `/api/validate` 校验失败返回 500，与契约的 400 不一致
- 前端结果清空后表格仍显示旧数据；SSE 断线误标运行状态徽标
- 前端按实现裁剪不支持的存储后端选项，避免选到必然校验失败的值

## [0.2.0] - 2026-11-15

面向"更强大、更简洁"的一次重构式增强，向后兼容 0.1.x 的配置与 CLI。

### 新增
- **极简高层 API**：`crawl(url, max_pages=20)` 一行抓取；`Session` 复用配置、`plan()` 只看计划、
  `crawl_async()` 供现有事件循环调用。全部通过延迟导入暴露在包顶层。
- **AIMD 自适应并发**：按滑动窗口的成功率与 p95 延迟乘性收敛 / 加性试探并发上限；
  只调整全局上限，不干预每域名礼貌限速。可通过 `adaptive_concurrency=false` 关闭。
- **桌面应用**：`opencrawler desktop` 启动本地 REST + SSE 服务，用 Edge/Chrome `--app`
  打开无地址栏独立窗口；可视化配置、启停、指标、日志流与结果表格。零 GUI 依赖。
- **exe 一键启动**：`desktop/OpenCrawlerLauncher.exe`（Win32 启动器，33 KB）与
  `desktop/build_exe.py`（PyInstaller 单文件约 17 MiB，目标机器无需 Python）。
- 引擎新增 `request_stop()` / `snapshot()`，支持外部优雅停机与实时状态查询。
- 三语言共用的桌面接口契约 [docs/DESKTOP_API.md](docs/DESKTOP_API.md)。
- 新增 16 项测试：自适应并发、高层 API、桌面 REST/SSE 端到端；共 39 项。

### 改进
- 桌面服务只监听 `127.0.0.1`，静态资源白名单、结果路径固定，避免路径穿越。
- 日志处理器异常隔离，SSE 断连自动清理；`dry-run` 可从桌面直接演练。
- README / PUBLISH.md / desktop/README.md 同步更新。

## [0.1.0] - 2026-11-14

首个公开版本，定位为教学用通用爬虫框架。

### 新增
- `asyncio` + `aiohttp` 高并发调度引擎：常驻 worker、全局/每域双重并发控制、公平队列
- SQLite WAL 持久优先队列：URL 去重、优先级、断点续爬、优雅停机、失败重试
- 合规层：robots.txt（Allow/Disallow/Crawl-delay/Sitemap）、本 UA 与通配组保守合并、
  失败默认拒绝、每域限速、429/Retry-After 自适应降速、nofollow 尊重
- 站点自适应抽取：HTML（元信息/正文/OpenGraph/JSON-LD）、JSON API、Sitemap/RSS XML、纯文本
- 配置化规则：CSS 选择器、XPath、轻量 JSONPath、正则、变换链（strip/url/int/float/join…）
- 扩展点：`parsers` / `pipelines` / `middlewares` 三类插件，支持同步与异步
- 存储：JSONL、SQLite、自定义后端；内容哈希去重
- 条件请求（ETag / Last-Modified）、流式体长上限、MIME 白名单
- 实时指标（日志 + `metrics.jsonl`）、三重熔断（页数/流量/时间）
- CLI：`crawl` / `fetch` / `demo` / `selftest` / `validate` / `init` / `version`
- 内置演示站点与 23 项单元/端到端测试
- 完整开源配套：MIT、ETHICS、ARCHITECTURE、CONTRIBUTING、SECURITY、CI、Issue 模板
- 压测脚本与一键发布脚本

[0.1.0]: https://github.com/OpenCrawlerLab/opencrawler-lab/releases/tag/v0.1.0
