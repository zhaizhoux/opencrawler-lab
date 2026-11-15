# 桌面服务接口契约（Python / Java / C++ 共用）

三个语言版本实现**同一套**本地 HTTP 接口，`desktop/web/` 里的前端文件可原样复用。
服务只绑定 `127.0.0.1`，默认端口 `8756`，无需认证（不对外监听）。

## 静态资源

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 返回 `desktop/web/index.html` |
| GET | `/app.css` | 样式表 |
| GET | `/app.js` | 前端逻辑 |

## REST

| 方法 | 路径 | 请求体 | 响应 |
| --- | --- | --- | --- |
| GET | `/api/status` | — | 运行快照，见下方字段 |
| GET | `/api/config` | — | 当前配置对象（全量字段） |
| POST | `/api/config` | 配置对象的部分字段 | `{ok, config}`；运行中返回 409 |
| POST | `/api/validate` | 配置对象 | `{valid, warnings, config}` 或 400 `{valid:false,error}` |
| POST | `/api/start` | 配置对象，含 `seeds: string[]` | `{ok, status}`；无种子 400，重复启动 409 |
| POST | `/api/stop` | — | `{ok}`；无任务时也返回 200（幂等） |
| GET | `/api/results?limit=100` | — | `{items: [...]}`（JSONL 末尾 N 条） |
| GET | `/api/logs?since=<seq>` | — | `{seq, items: [{seq,level,message,source}]}` |
| GET | `/api/export` | — | 下载 `items.jsonl`；无文件 404 |

`status` 至少包含：

```json
{
  "version": "0.2.0",
  "running": false,
  "requests": 0, "succeeded": 0, "failed": 0, "items": 0,
  "requests_per_second": 0.0, "elapsed_seconds": 0.0,
  "inflight": 0, "frontier": {"queued": 0, "done": 0},
  "adaptive": {"enabled": true, "limit": 32},
  "summary": null, "error": "", "output_dir": "./output"
}
```

`config` 至少包含前端用到的字段：`seeds`, `concurrency`, `per_domain_concurrency`,
`default_delay_ms`, `per_domain_rps`, `max_pages`, `max_depth`, `time_budget_seconds`,
`storage`, `output_dir`, `extract_mode`, `respect_robots`, `obey_crawl_delay`,
`adaptive_concurrency`, `dedupe_content`, `follow_sitemaps`。各语言可以扩展额外字段，
前端会忽略未知字段、并在提交时原样回传。

## SSE

`GET /api/events`，`Content-Type: text/event-stream`，每秒推送一次：

```
event: log
data: {"seq":12,"level":"INFO","message":"任务启动：2 个种子","source":"desktop"}

event: status
data: {"version":"0.2.0","running":true,...}
```

前端用 `EventSource` 订阅；连接中断时 HTTP 层直接关闭即可，前端会自动重连。

## 安全边界

- 禁止监听 `0.0.0.0`，禁止把服务暴露到局域网；
- 静态资源只允许白名单文件名，拒绝路径穿越；
- 结果读取只从配置的 `output_dir/items.jsonl` 取，禁止任意路径；
- 所有实现都不得因为桌面接口而降低合规默认值。
