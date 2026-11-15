# 桌面服务接口契约 v0.3（Python / Java / C++ 共用）

三个语言版本实现**同一套**本地 HTTP 接口，`desktop/web/` 里的三个前端文件
（`index.html` / `app.css` / `app.js`）在三仓库中保持**字节级一致**，可原样复用。
服务只绑定 `127.0.0.1`，默认端口分别为 8756（Python）/ 8757（Java）/ 8758（C++），
无需认证（不对外监听）。

前端遵循「新字段优先、旧服务端降级可用」：缺少 `implementation`、`total`、
`uptime_seconds` 等字段时会自动回退，不会因为某个实现版本略旧而报错。

## 静态资源

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` 或 `/index.html` | `text/html; charset=utf-8` |
| GET | `/app.css` | `text/css; charset=utf-8` |
| GET | `/app.js` | `application/javascript; charset=utf-8` |

静态资源必须带正确的 `Content-Type`（含字符集），且只允许白名单文件名。

## REST

| 方法 | 路径 | 请求体 | 响应 |
| --- | --- | --- | --- |
| GET | `/api/info` | — | 实现元信息，见下方 |
| GET | `/api/status` | — | 运行快照，见下方字段 |
| GET | `/api/config` | — | 当前配置对象（全量字段） |
| POST | `/api/config` | 配置对象的部分字段 | `{ok, config}`；运行中返回 409 |
| POST | `/api/validate` | 配置对象 | 200 `{valid:true, warnings, config}` 或 400 `{valid:false, error}` |
| POST | `/api/start` | 配置对象，含 `seeds: string[]` | `{ok, status}`；无种子 400，重复启动 409 |
| POST | `/api/stop` | — | `{ok}`；无任务时也返回 200（幂等） |
| GET | `/api/results` | — | `{items, total, limit, offset}`，见下方查询参数 |
| GET | `/api/logs?since=<seq>` | — | `{seq, items: [{seq,level,message,source}]}` |
| GET | `/api/export` | — | 下载 `items.jsonl`；无文件 404 |
| GET | `/api/events` | — | SSE 流，见下方 |

### `/api/info`（v0.3 新增）

```json
{
  "implementation": "python",
  "language": "Python 3.13.14",
  "version": "0.3.0",
  "platform": "Windows 10",
  "started_at": "2026-11-15T05:00:00+00:00",
  "uptime_seconds": 123.4,
  "endpoints": ["/api/info", "..."],
  "compliance_defaults": ["遵守 robots.txt", "..."],
  "storage_backends": ["jsonl", "sqlite", "none"],
  "result_scan_limit": 20000
}
```

`implementation` 取值固定为 `python` / `java` / `cpp`。前端据此显示实现徽标，
并裁剪不支持的选项（例如只有 Python 提供 SQLite 后端）。

### `status` 至少包含

```json
{
  "version": "0.3.0",
  "implementation": "python",
  "platform": "Windows",
  "uptime_seconds": 12.5,
  "running": false,
  "requests": 0, "succeeded": 0, "failed": 0, "skipped": 0,
  "items": 0, "duplicates": 0, "bytes": 0, "links_discovered": 0,
  "requests_per_second": 0.0, "elapsed_seconds": 0.0,
  "inflight": 0, "frontier": {"queued": 0, "done": 0},
  "adaptive": {"enabled": true, "limit": 32},
  "summary": null, "error": "", "output_dir": "./output"
}
```

各语言可以扩展额外字段（如 `status_codes` / `domains` / `not_modified`），
前端会忽略未知字段。**空闲态也必须返回全部数值字段**（补 0），避免前端分别兜底。

### `/api/results` 查询参数（v0.3 扩展）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `limit` | 100 | 1–1000，返回窗口大小 |
| `offset` | 0 | 从**最新一条**往历史方向偏移，用于加载更早的结果 |
| `q` | 空 | 对 `url` 与 `data.title`/`data.name` 做大小写无关子串匹配 |
| `kind` | 空 | 精确匹配 `kind`（如 `page` / `sitemap` / `feed`） |

响应：

```json
{"items": [...], "total": 137, "limit": 100, "offset": 0}
```

`total` 是扫描窗口（末尾最多 `result_scan_limit` 行）内的匹配条数；
`items` 按文件顺序（旧→新）返回，前端负责反转成最新在前。
三种实现都同时支持**服务端筛选**与前端本地二次筛选，行为完全一致。

`items` 的每行结构与三语言存储层一致：

```json
{"url": "...", "kind": "page", "content_hash": "...", "crawled_at": "...",
 "data": {"title": "...", "status": 200, "elapsed_ms": 12, "...": "..."}}
```

Java 版用 `hash` / `fetched_at` 作为等价字段；前端同时兼容两种命名，
也兼容旧版服务端直接写扁平条目的情况（`it.data || it`）。

### 统一错误约定

- `/api/validate` 校验失败一律 **400 + `{valid:false, error}`**，不使用 500；
- 其它接口出错返回对应 HTTP 状态 + `{error: "..."}`；
- 前端 `fetch` 会把 `error` 字段显示为中文提示，不会静默失败。

## SSE

`GET /api/events`，`Content-Type: text/event-stream; charset=utf-8`，每秒推送一次：

```
event: log
data: {"seq":12,"level":"INFO","message":"任务启动：2 个种子","source":"desktop"}

event: status
data: {"version":"0.3.0","running":true,...}
```

前端用 `EventSource` 订阅并维护连接状态徽标（实时 / 重连中 / 轮询模式 /
服务已断开）；同时每 3 秒轮询 `/api/status` 作为兜底，SSE 不可用时界面仍可用。

## 前端能力（v0.3）

12 个实时指标卡 + 60 秒吞吐趋势折线；结果表支持搜索、类型筛选、HTTP 状态、
耗时、点击展开完整 JSON 详情、CSV 导出；日志支持级别/关键字过滤、暂停缓冲、
清空、自动滚动开关；配置支持多份本地预设（保存 / 载入 / 删除 / 导入 / 导出）、
服务端保存、校验、恢复默认；深色 / 浅色主题持久化；
快捷键 `Ctrl+Enter` 启动、`Ctrl+.` 停止、`/` 聚焦搜索、`Esc` 关闭详情。

## 安全边界

- 禁止监听 `0.0.0.0`，禁止把服务暴露到局域网；
- 静态资源只允许白名单文件名，拒绝路径穿越；
- 结果读取只从配置的 `output_dir/items.jsonl` 取，禁止任意路径；
- 所有来自抓取结果的文本在前端渲染前一律转义；
- 所有实现都不得因为桌面接口而降低合规默认值。
