# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

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
