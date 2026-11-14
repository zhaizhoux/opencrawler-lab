"""内置演示/测试站点：无需访问公网即可完整学习、演示与自测爬虫行为。

包含：robots.txt（含 Crawl-delay / Disallow / Sitemap）、sitemap.xml、RSS、
JSON API、带 noindex/nofollow 的页面、外链、静态资源、500 错误页与慢响应。
"""
from __future__ import annotations

import asyncio
import json

from aiohttp import web

PAGE_BODIES = {
    1: "异步爬虫的调度器负责把待抓 URL 放入优先队列，并按域名限速。",
    2: "robots.txt 是站点与爬虫之间的约定，学习爬虫必须先学会尊重它。",
    3: "结构化抽取可以使用 CSS 选择器、XPath、JSONPath 或正则表达式。",
}

_HEAD = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{title} · OpenCrawlerLab 演示站</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
{extra}
<link rel="canonical" href="{canonical}">
</head><body><nav>演示站点导航</nav><main>"""


def _page(request: web.Request, number: int, *, title: str, desc: str, extra: str = "") -> str:
    base = f"{request.scheme}://{request.host}"
    canonical = f"{base}/" if number == 0 else f"{base}/page/{number}"
    body = PAGE_BODIES.get(number, "这是一个用于学习的公开演示页面，包含若干站内链接。")
    html = _HEAD.format(title=title, desc=desc, extra=extra, canonical=canonical)
    html += f"<h1>{title}</h1><article><p>{body}</p><p>正文段落二，用于测试文本抽取与字数统计。</p></article>"
    html += '<ul class="links">'
    for n in (1, 2, 3):
        html += f'<li><a href="/page/{n}">站内页面 {n}</a></li>'
    html += '<li><a href="/" rel="nofollow">首页（nofollow）</a></li>'
    html += '<li><a href="/style.css">样式表（应被后缀过滤）</a></li>'
    html += '<li><a href="https://www.example.org/out">外链（默认不跟随）</a></li>'
    html += '<li><a href="/admin/panel">管理页（默认黑名单）</a></li>'
    html += '<li><a href="/secret">robots 禁止页</a></li>'
    html += '<li><a href="/feed.xml">RSS 订阅</a></li>'
    html += '<li><a href="/api/items.json">JSON 接口</a></li>'
    html += "</ul><footer>页脚文本</footer></main></body></html>"
    return html


async def index(request: web.Request) -> web.Response:
    extra = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"WebSite","name":"OpenCrawlerLab Demo"}'
        "</script>"
    )
    return web.Response(
        text=_page(request, 0, title="首页", desc="通用爬虫学习用演示站点", extra=extra),
        content_type="text/html", charset="utf-8",
    )


async def page(request: web.Request) -> web.Response:
    number = int(request.match_info["number"])
    if number not in PAGE_BODIES:
        raise web.HTTPNotFound()
    return web.Response(
        text=_page(request, number, title=f"页面 {number}", desc=f"演示页面 {number} 的描述"),
        content_type="text/html", charset="utf-8",
    )


async def robots(request: web.Request) -> web.Response:
    base = f"{request.scheme}://{request.host}"
    return web.Response(
        text=(
            "User-agent: *\n"
            "Crawl-delay: 0\n"
            "Disallow: /secret\n"
            "Allow: /\n"
            f"Sitemap: {base}/sitemap.xml\n"
        ),
        content_type="text/plain",
    )


async def sitemap(request: web.Request) -> web.Response:
    base = f"{request.scheme}://{request.host}"
    urls = [""] + [f"/page/{n}" for n in PAGE_BODIES]
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    body += "".join(
        f"<url><loc>{base}{path}</loc><changefreq>weekly</changefreq><priority>0.5</priority></url>"
        for path in urls
    )
    return web.Response(text=body + "</urlset>", content_type="application/xml")


async def feed(request: web.Request) -> web.Response:
    items = "".join(
        f"<item><title>文章 {n}</title><link>{request.scheme}://{request.host}/page/{n}</link>"
        f"<pubDate>2026-01-0{n}T00:00:00Z</pubDate><description>摘要 {n}</description></item>"
        for n in (1, 2, 3)
    )
    return web.Response(
        text=f'<?xml version="1.0"?><rss version="2.0"><channel><title>演示订阅</title>{items}</channel></rss>',
        content_type="application/rss+xml",
    )


async def api(request: web.Request) -> web.Response:
    return web.Response(
        text=json.dumps(
            {
                "count": 3,
                "items": [
                    {"id": n, "title": f"条目 {n}", "url": f"/page/{n}"}
                    for n in (1, 2, 3)
                ],
                "next": None,
            },
            ensure_ascii=False,
        ),
        content_type="application/json",
    )


async def secret(request: web.Request) -> web.Response:
    return web.Response(text="<html><body><h1>不该被抓取</h1></body></html>", content_type="text/html")


async def admin(request: web.Request) -> web.Response:
    return web.Response(text="<html><body><h1>管理页</h1></body></html>", content_type="text/html")


async def flaky(request: web.Request) -> web.Response:
    return web.Response(status=503, text="service unavailable")


async def slow(request: web.Request) -> web.Response:
    await asyncio.sleep(1)
    return web.Response(text="<html><body><h1>慢页面</h1></body></html>", content_type="text/html")


async def notfound_handler(request: web.Request) -> web.Response:
    return web.Response(status=404, text="not found")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/page/{number}", page)
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/feed.xml", feed)
    app.router.add_get("/api/items.json", api)
    app.router.add_get("/secret", secret)
    app.router.add_get("/admin/panel", admin)
    app.router.add_get("/flaky", flaky)
    app.router.add_get("/slow", slow)
    app.router.add_route("*", "/style.css", notfound_handler)
    return app


async def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"演示站点已启动: http://{host}:{port}/  (Ctrl+C 退出)")
    await asyncio.Event().wait()
