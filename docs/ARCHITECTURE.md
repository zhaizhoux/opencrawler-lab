# 架构与扩展点

## 数据流

```
                    ┌──────────────────────────────┐
                    │ Config (JSON/YAML/TOML + CLI) │
                    └──────────────┬───────────────┘
                                   ▼
 seeds ──► Frontier (SQLite WAL, 状态机 0/1/2/3, 优先级 + 域名轮转)
                    │
                    ▼
        ┌───────────────────────────────┐
        │ Engine：常驻 worker 池 + 调度循环│◄──── 优雅停机 / 三重熔断
        └───────────────┬───────────────┘
                        ▼
 Middleware.before ─► RobotsPolicy ─► DomainLimiter ─► Fetcher ─► Middleware.after
   (可丢弃任务)        (按 origin 缓存)   (间隔+信号量)   (aiohttp)     (可丢弃响应)
                                                            │
                                                            ▼
                                     Extractor ──► 新链接回到 Frontier
                                     (HTML/JSON/XML + 规则 + 插件)
                                            │
                                            ▼
                     Pipeline(内容哈希去重 → 插件 → JSONL / SQLite)
                                            │
                                            ▼
                        Metrics(日志 + metrics.jsonl + 最终摘要)
```

## 模块职责

| 模块 | 职责 | 关键设计 |
| --- | --- | --- |
| `config.py` | 配置加载/校验 | 未知键直接报错，避免拼写错误静默生效；相对路径按配置文件目录解析 |
| `frontier.py` | 持久优先队列 | URL 主键天然去重；`pop_batch` 多域名轮转保证公平；状态落盘支持续爬 |
| `robots.py` | 合规 | origin（含端口）级缓存；本 UA 组 + 通配组保守合并；失败默认拒绝 |
| `ratelimit.py` | 限速 | 每域 `asyncio.Lock` 串行化间隔计算 + `Semaphore` 并发槽；429 惩罚窗口 |
| `fetcher.py` | 下载 | 连接池、流式体长上限、MIME 白名单、条件请求、Retry-After、指数退避 |
| `extractor.py` | 解析 | 内容类型自适应；bs4/lxml 可选，缺依赖时降级到标准库 HTMLParser |
| `pipeline.py` | 输出 | 内容哈希去重 + 插件链 + 存储抽象 |
| `metrics.py` | 观测 | 请求/状态/流量/速率/队列快照，周期性写 JSONL |
| `engine.py` | 编排 | 调度循环、单任务异常隔离、信号处理、收尾等待 |

## 并发模型

- 全局并发由 `len(inflight tasks) <= concurrency` 控制，不额外套信号量；
- 每域名并发由 `Frontier.pop_batch(inflight=...)` 与 `DomainLimiter.semaphore` 双重控制；
- 每域名最小间隔由 `DomainLimiter` 计算：
  `max(default_delay_ms, per_domain_delay_ms, Crawl-delay, 1000/per_domain_rps)`；
- SQLite 操作短且同步，放在事件循环里执行（WAL + NORMAL），避免跨线程连接问题；
- 所有网络 I/O 都是 `asyncio` 协程，无阻塞调用（文件写入为小量追加）。

## 三个扩展点

所有插件都写成 `"模块:函数"` 或 `"相对/绝对.py:函数"`：

1. **`parsers`**：`fn(response) -> ExtractResult | dict | None`
   返回非空结果即接管该响应的解析（适合私有 JSON 结构）。
2. **`pipelines`**：`fn(item) -> Item | dict | False | None`
   返回 `False` 丢弃，`dict` 合并进 `item.data`，`Item` 替换条目。
3. **`middlewares`**：`fn(request, response=None) -> bool | Request | Response | None`
   抓取前 `response=None`，抓取后传入响应；返回 `False` 丢弃任务。

支持普通函数与 `async def`，插件异常被隔离并记录，不会拖垮引擎。

## 自定义存储后端

继承 `storage.Storage`，实现 `async write(item)` / `async close()`，
然后在 `storage.create_storage()` 中注册即可。状态队列与结果存储相互独立，
替换成 Redis / 消息队列 / 对象存储都不影响其他模块。

## 为什么"高并发"仍然"有礼貌"

并发数只决定**同时在途的请求数**；真正的礼貌性由每域名最小间隔与 RPS 上限决定。
框架把这两件事分开：`concurrency` 提高多域名吞吐，`per_domain_*` 保证单站不被打爆。
`scripts/benchmark.py` 用本机内存站点演示这一点。
