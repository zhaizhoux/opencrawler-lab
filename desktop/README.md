# 桌面应用与 exe 一键启动

这一层**不包含任何爬虫逻辑**，只是把 `opencrawler.server` 包装成一个本地桌面程序：
启动 `127.0.0.1` 上的服务，再用 Edge / Chrome 的 `--app` 模式打开一个无地址栏的独立窗口。
因此不需要 tkinter / Qt / Electron，Windows、Linux、macOS 表现一致，且与 Java、C++ 版本共用同一套前端。

## 三种启动方式

| 方式 | 命令 | 适用场景 |
| --- | --- | --- |
| 命令行 | `python -m opencrawler desktop` | 开发调试 |
| 源码 | `python desktop/launcher.py --port 8756` | 未安装为包 |
| **exe 一键** | 双击 `OpenCrawlerLauncher.exe` | 日常使用，无需记命令 |
| exe 带参数 | `OpenCrawlerLauncher.exe --no-browser --port 9000` | 参数原样转给主程序，便于调试 |

`OpenCrawlerLauncher.exe` 是一个 44 KB 的 Win32 GUI 启动器（源码 `win_launcher.cpp`，无控制台、无依赖）：
启动器放在项目根目录、`desktop/` 或 `dist/` 下都能自动定位
`dist/OpenCrawlerLab.exe` 或 `desktop/launcher.py`；优先用打包版，没有则退回
`pythonw.exe desktop/launcher.py`；两者都找不到时给出中文错误提示，不会静默失败。

重新编译启动器：

```bash
g++ -O2 -s -mwindows desktop/win_launcher.cpp -o desktop/OpenCrawlerLauncher.exe
```

## 生成完全独立的单文件 exe

```bash
python -m pip install pyinstaller
python desktop/build_exe.py                 # 生成 dist/OpenCrawlerLab.exe
python desktop/build_exe.py --console      # 排错时保留控制台
```

产物自带 Python 运行时、aiohttp 与全部依赖（约 17 MiB），**目标机器不需要安装 Python**。
双击后自动打开桌面窗口；关闭服务窗口或结束进程即停止。构建产物 `dist/`、`build/` 已被 `.gitignore` 排除，
不进仓库，可通过 GitHub Release 分发。

## 桌面窗口能做什么

- 可视化编辑全部常用配置（种子、并发、限速、页数/深度/时间预算、存储、合规开关、自适应并发）
- 一键启动 / 优雅停止（会保存断点，下次可续爬）
- SSE 实时推送：12 个指标卡、60 秒吞吐趋势折线、并发上限变化、日志流、抓取结果
- 结果支持搜索 / 类型筛选 / 翻页 / JSON 详情 / CSV 导出；日志支持过滤与暂停
- 配置预设（本地保存 / 载入 / 导入导出）、校验、恢复默认、导出 `items.jsonl`、深浅主题

服务**只监听 127.0.0.1**，不对外开放；不会读取仓库外的文件，也不会把抓取数据发到任何地方。

## 接口契约

`web/` 目录里的 `index.html` / `app.css` / `app.js` 不依赖具体语言实现，只依赖
`docs/DESKTOP_API.md` 中列出的 REST + SSE 接口。Java 与 C++ 版本复用同一份前端文件，
所以三个实现的桌面体验完全一致。

## 合规

桌面界面默认开启 `robots.txt`、`Crawl-delay`、内容去重与自适应并发，且提供"仅抓取公开页面"的常驻提示。
界面**不提供**任何关闭合规保护后绕过登录墙/验证码的能力；`respect_robots` 开关仅供在自有站点上做教学实验。

## v0.3 前端能力

`web/` 三文件与另外两版字节级一致。除原有配置、启停、指标、日志、结果表格外，新增：
吞吐趋势折线、结果搜索/类型筛选/JSON 详情/CSV 导出、日志级别过滤与暂停缓冲、
多份配置预设（localStorage 持久化，支持 JSON 导入导出）、深色/浅色主题、
SSE 连接状态徽标与轮询兜底、键盘快捷键。

前端会先请求 `/api/info` 判断连的是 Python / Java / C++ 哪一版并显示实现徽标；
旧版服务端没有该接口时自动降级，不会报错。
