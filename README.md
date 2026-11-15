# OpenCrawlerLab · 通用网站爬虫学习框架

> 一个**用于学习**的、开源、合规、异步高并发的通用网站爬虫框架。
> 面向"各种网站"的自适应抽取：HTML / JSON API / XML(Sitemap、RSS) / 纯文本，
> 一套配置即可适配，不需要为每个站点重写爬虫。

[![CI](https://github.com/zhaizhoux/opencrawler-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/zhaizhoux/opencrawler-lab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

---

## ⚠️ 先读这一段

本项目是**教学软件**。它默认遵守 `robots.txt`、默认限速、默认限深限页、默认不跟随外链，
并且**明确不提供**任何绕过验证码、登录墙、付费墙、IP 封锁或浏览器指纹检测的能力。

请只抓取**公开、且你被允许访问**的页面，遵守目标站点的服务条款与适用法律，
尊重版权与个人数据。详见 [ETHICS.md](ETHICS.md)。作者对滥用行为不承担责任。

---

## 为什么是"通用"的

| 网站形态 | 框架的处理方式 |
| --- | --- |
| 传统 HTML 页面 | 自动抽取 title / description / canonical / h1 / 正文 / OpenGraph / JSON-LD / 链接 |
| 前后端分离 / JSON API | 自动解析 JSON，递归发现 `url`、`href`、`link`、`next` 等字段中的链接 |
| Sitemap / RSS / Atom | 解析 `<loc>`、`<link>`、`<guid>`，支持 sitemap index 递归 |
| 需要定制字段 | 配置化规则：CSS 选择器、XPath、轻量 JSONPath、正则、变换链 |
| 特殊/私有结构 | Python 插件：`parsers` / `pipelines` / `middlewares` 三个扩展点 |
| 多语言 / 多种编码 | 按 HTTP 头 / BOM / HTML meta 推断编码， UTF-8 / GB18030 / Latin-1 兜底 |
| 静态资源、后台路径 | 后缀与 URL 黑名单默认过滤 |

**"高并发 + 长时间运行"**：`asyncio` 常驻 worker、连接池、每域名独立信号量与令牌间隔、
SQLite WAL 持久队列、优先级 + 多域名公平调度、条件请求（ETag / Last-Modified）、
指数退避与 `Retry-After`、429 自适应降速、实时指标、优雅停机（Ctrl+C 保存进度）、
**断点续爬**（重跑同一命令即可继续，不重复抓）。

---

## 快速开始

```bash
# 1. 安装（建议虚拟环境）
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[full,dev]"                      # 或 pip install -r requirements.txt

# 2. 不访问公网，先跑内置自检（内存站点 + 完整抓取 + 合规断言）
python -m opencrawler selftest

# 3. 看看演示站点长什么样
python -m opencrawler demo --port 8765
# 另开一个终端：
python -m opencrawler crawl --seed http://127.0.0.1:8765/ --out ./output --concurrency 8 --delay-ms 0

# 4. 调试单个页面的抽取结果（写规则时最有用）
python -m opencrawler fetch https://example.com/

# 5. 正式任务用配置文件
python -m opencrawler init -o crawler.config.json
python -m opencrawler crawl -c crawler.config.json --dry-run     # 先看计划，不发请求
python -m opencrawler crawl -c crawler.config.json

# 6. 或者直接打开桌面控制台（自动开一个独立窗口）
python -m opencrawler desktop
# Windows 也可以双击 desktop/OpenCrawlerLauncher.exe
```

输出在 `output/`：`items.jsonl`（每行一条结构化记录）、`metrics.jsonl`（周期性指标）、
`state.sqlite3`（队列状态，续爬用）、`items.sqlite3`（选 SQLite 后端时）。

---

## 配置文件

`JSON` / `YAML` / `TOML` 都支持；命令行参数优先级更高。

```json
{
  "seeds": ["https://example.com/"],
  "allowed_domains": ["example.com"],
  "max_depth": 4,
  "max_pages": 5000,
  "concurrency": 32,
  "per_domain_concurrency": 4,
  "default_delay_ms": 500,
  "respect_robots": true,
  "extract_mode": "both",
  "storage": "jsonl",
  "output_dir": "./output",
  "rules": [
    {
      "name": "article",
      "url_pattern": "/article/",
      "fields": {
        "title":  {"selector": "h1", "transform": "strip"},
        "author": {"selector": ".byline", "transform": "strip"},
        "date":   {"selector": "time", "attr": "datetime"},
        "tags":   {"selector": ".tag", "many": true, "limit": 10},
        "price":  {"regex": "¥\\s*([0-9.]+)", "transform": "float"},
        "h1_xpath": {"xpath": "//h1/text()"},
        "list_count": {"json_path": "data.total", "transform": "int"}
      }
    }
  ]
}
```

关键配置项：

| 分类 | 字段 | 默认 | 说明 |
| --- | --- | --- | --- |
| 范围 | `seeds` / `allowed_domains` | 自动 | 起点与允许域名（含子域） |
| 范围 | `follow_external` / `max_depth` | `false` / `5` | 是否跨域、最大深度 |
| 范围 | `deny_url_patterns` / `allow_url_patterns` | 后台路径等 | 正则黑白名单 |
| 合规 | `respect_robots` / `obey_crawl_delay` | `true` | robots.txt 与 Crawl-delay |
| 合规 | `robots_on_error` | `deny` | 无法确认 robots 时保守拒绝 |
| 合规 | `user_agent` / `default_delay_ms` | 明示 UA / `500` | 请改成带联系方式的 UA |
| 并发 | `concurrency` / `per_domain_concurrency` | `32` / `4` | 全局 / 单域名并发 |
| 稳定 | `retries` / `backoff_base` / `request_timeout` | `2` / `0.8` / `20` | 重试与超时 |
| 稳定 | `max_pages` / `max_bytes` / `time_budget_seconds` | `1000` / `512MiB` / `0` | 三重熔断，0 表示不限时 |
| 抽取 | `extract_mode` | `auto` | `auto` / `rules` / `both` / `raw` |
| 输出 | `storage` / `dedupe_content` / `save_raw` | `jsonl` / `true` / `false` | 存储后端与去重 |
| 扩展 | `parsers` / `pipelines` / `middlewares` | `[]` | `"模块:函数"` 或 `"路径.py:函数"` |

完整示例见 [examples/config.full.yaml](examples/config.full.yaml)，插件示例见
[examples/custom_plugin.py](examples/custom_plugin.py)。

---

## 输出样例

```json
{
  "url": "https://example.com/article/1",
  "kind": "page",
  "content_hash": "9f2c...",
  "crawled_at": "2026-11-14T12:00:00Z",
  "data": {
    "title": "文章标题", "description": "...", "canonical": "...",
    "h1": "文章标题", "text": "正文…", "text_length": 1234,
    "meta": {"description": "..."}, "open_graph": {}, "json_ld": [],
    "status": 200, "content_type": "text/html", "size": 20480,
    "elapsed_ms": 143, "rules": {"article": {"title": "文章标题", "tags": ["A", "B"]}}
  }
}
```

---

## 架构

```
seeds ──> Frontier(SQLite 优先队列, 去重/续爬)
              │ 按域名公平出队
              ▼
        N 个常驻 asyncio worker（全局并发上限）
              │
   Middleware.before → RobotsPolicy → DomainLimiter(限速+并发槽)
              │
        Fetcher(aiohttp 连接池 / 超时 / 体长限制 / 条件请求 / 退避)
              │
   Middleware.after → Extractor(HTML/JSON/XML + 规则 + 插件)
              │                    └── 新链接回到 Frontier
              ▼
     Pipeline(内容去重 → 插件 → JSONL / SQLite)
              │
        Metrics(实时日志 + metrics.jsonl)
```

模块清单与扩展点说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 断点续爬与优雅停机

- 每个 URL 的状态（`queued / inflight / done / failed`）都写在 SQLite WAL 中；
- `Ctrl+C` 或 `SIGTERM`：停止取新任务，等在途请求收尾（最多 15 秒），保存进度后退出；
- 进程被强杀也没关系：下次启动时 `inflight` 自动还原为 `queued`；
- 想从头开始：删除 `output/state.sqlite3*`。

---

## 性能压测

```bash
python scripts/benchmark.py            # 内存生成 400 个页面，测 4/16/64 并发的 req/s
```

压测只打本机内存站点，不会对公网造成任何压力。

---

## 极简 API（0.2.0 新增）

需要写脚本时，不用碰 `Config` 和事件循环：

```python
from opencrawler import crawl, plan, Session, crawl_async

plan("https://example.com/", max_pages=20)          # 只看计划，零网络请求
report = crawl("https://example.com/", max_pages=20)  # 一行抓取，返回指标摘要

with Session(concurrency=64, output_dir="./out") as s:
    s.run(["https://a.example/", "https://b.example/"])   # 配置复用
    report = s.run(["https://c.example/"], max_pages=10)  # 单次覆盖参数

# 在已有的 async 应用里
report = await crawl_async("https://example.com/", storage="jsonl")
```

精细控制仍用原来的 `Config` + `Crawler`；`crawler.request_stop()` 支持外部优雅停机，
`crawler.snapshot()` 返回实时指标。

## 桌面应用与 exe 一键启动（0.2.0 新增）

`python -m opencrawler desktop` 会在 `127.0.0.1:8756` 起一个本地服务，并用
Edge / Chrome 的 `--app` 模式打开**无地址栏的独立桌面窗口**：可视化编辑配置、启停任务、
实时看 6 个指标与日志流、浏览与导出抓取结果。不依赖 tkinter / Qt / Electron。

Windows 上双击 `desktop/OpenCrawlerLauncher.exe`（33 KB Win32 启动器）即可一键运行；
执行 `python desktop/build_exe.py` 可生成完全独立的 `dist/OpenCrawlerLab.exe`（约 17 MiB，
目标机器无需 Python）。详见 [desktop/README.md](desktop/README.md)。

前端只依赖 [docs/DESKTOP_API.md](docs/DESKTOP_API.md) 定义的 REST + SSE 契约，
**Java 版与 C++ 版复用同一套前端**，三种实现的桌面体验一致：

| 仓库 | 语言 | 并发模型 |
| --- | --- | --- |
| [opencrawler-lab](https://github.com/zhaizhoux/opencrawler-lab) | Python 3.10+ | `asyncio` + aiohttp |
| [opencrawler-java](https://github.com/zhaizhoux/opencrawler-java) | Java 21 | 虚拟线程（Loom） |
| [opencrawler-cpp](https://github.com/zhaizhoux/opencrawler-cpp) | C++20 | 固定线程池 + WinHTTP / POSIX socket（零第三方依赖） |

## 自适应并发（0.2.0 新增）

固定并发数在真实站点上常常不是最优。`adaptive_concurrency`（默认开）用一个滑动窗口的
成功率与 p95 延迟做 AIMD：错误率或延迟越界时并发乘性降到 80%，健康时按 1/8 缓慢加性增加，
上下限由配置约束。它**只调整全局上限**，每域名限速与 robots 规则始终独立生效。

---

## 已开源到 GitHub

三个版本各自独立开源、共用同一套桌面前端与 REST + SSE 接口契约：

| 仓库 | 状态 | 文件数 |
| --- | --- | --- |
| https://github.com/zhaizhoux/opencrawler-lab | Public · `main` · CI 通过 | 59 |
| https://github.com/zhaizhoux/opencrawler-java | Public · `main` · CI 通过 | 34 |
| https://github.com/zhaizhoux/opencrawler-cpp | Public · `main` · CI 通过 | 27 |

均保留完整提交历史与作者信息，无凭证或抓取数据入库。欢迎 Star / Issue / PR。

`scripts/publish_github.py` 是配套的一键发布脚本，支持两条通道：标准 `git push`，以及
`github.com` 不可达时自动切换的 `api.github.com` Git Data API（重放完整提交历史）。
它还处理了空仓库初始化、fine-grained PAT 无权建仓等边界情况。

```bash
python scripts/publish_github.py --dry-run       # 不联网、不需要 Token，先列发布计划
python scripts/publish_github.py --check-token   # 验证 Token 身份与权限
python scripts/publish_github.py --skip-create   # 仓库已存在时直接推送
```

Token 放在仓库之外的 `~/.config/opencrawler-lab/token`（或环境变量 `GITHUB_TOKEN`），
`.gitignore` 已排除 `.env` / `*.token`，凭证绝不入库。
完整步骤与排障记录见 [PUBLISH.md](PUBLISH.md)。

---

## 测试

```bash
python -m pytest tests -q
python -m opencrawler selftest
ruff check src tests
```

CI 在 Python 3.10 ~ 3.13 上运行全套测试（见 `.github/workflows/ci.yml`）。

---

## 常见问题

**Q：为什么只抓到几页？** 检查 `max_depth` / `max_pages` / `allowed_domains` /
`deny_url_patterns`，并用 `--log-level DEBUG` 看被过滤的原因（DEBUG 日志会打印 robots 跳过原因）。

**Q：能抓需要登录的页面吗？** 框架不提供绕过登录/验证码的能力。你可以用 `extra_headers`
访问**你自己拥有或已获授权**的接口，但请自行承担合规责任。

**Q：JS 渲染的页面怎么办？** `render_js` 是留给使用者的声明式扩展点，框架不内置无头浏览器，
也不做任何反检测。推荐优先寻找站点公开的 JSON API 或 Sitemap。

**Q：如何分布式扩展？** 当前单机 asyncio 已能压满普通网络；若需多机，把 `Frontier` 替换为
Redis 队列即可（`frontier.py` 的接口只有 add / pop_batch / mark_done / mark_failed）。

---

## 目录结构

```
src/opencrawler/
  cli.py         命令行        config.py      配置与校验
  engine.py      调度引擎      frontier.py    持久化优先队列
  fetcher.py     HTTP 下载     robots.py      robots.txt 策略
  ratelimit.py   每域限速      extractor.py   自适应抽取 + 规则
  pipeline.py    输出管线      storage/       JSONL / SQLite 后端
  plugins.py     插件加载      metrics.py     指标
  demo.py        内置演示站点  models.py      数据模型
tests/           23 项单元测试 + 端到端测试
examples/        配置与插件示例
scripts/         压测与一键发布脚本
```

---

## 参与贡献 / 安全

见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [SECURITY.md](SECURITY.md)。
MIT 许可，详见 [LICENSE](LICENSE)。

**再次提醒：这是学习项目，请做一个有礼貌的爬虫作者。**
