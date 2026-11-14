from opencrawler.config import Config
from opencrawler.extractor import Extractor
from opencrawler.models import Request, Response

HTML = """<!doctype html><html lang="zh-CN"><head>
<title>测试页面</title><meta name="description" content="页面描述">
<meta property="og:title" content="社交标题"><link rel="canonical" href="/canonical">
<script type="application/ld+json">{"@type":"Article","headline":"LD 标题"}</script>
</head><body><nav>导航</nav><main><h1>主标题</h1>
<p>这是第一段正文。</p><p>这是第二段正文。</p>
<a href="/a">A</a><a href="/b" rel="nofollow">B</a>
<a href="https://external.example/x">外部</a>
<a href="/pic.png">图片</a><a href="/admin/panel">后台</a>
</main><footer>页脚</footer><script>var x = 1;</script></body></html>"""


def _response(body: bytes = HTML.encode(), mime: str = "text/html", url: str = "https://example.com/p"):
    return Response(
        request=Request(url), status=200, final_url=url,
        headers={"content-type": mime}, body=body, elapsed_ms=12, content_type=mime,
    )


def test_auto_html_extraction():
    cfg = Config.from_dict({"seeds": ["https://example.com"]})
    result = Extractor(cfg).extract(_response())
    assert result.item["title"] == "测试页面"
    assert result.item["h1"] == "主标题"
    assert result.item["description"] == "页面描述"
    assert result.item["open_graph"]["title"] == "社交标题"
    assert result.item["lang"] == "zh-CN"
    assert result.item["json_ld"][0]["@type"] == "Article"
    assert "第一段正文" in result.item["text"] and "导航" not in result.item["text"]
    assert len(result.content_hash) == 64
    urls = [r.url for r in result.links]
    assert "https://example.com/a" in urls
    assert "https://example.com/b" not in urls          # nofollow
    assert "https://external.example/x" not in urls     # 跨域
    assert not any(u.endswith(".png") for u in urls)    # 静态资源
    assert not any("/admin" in u for u in urls)         # 默认黑名单


def test_rules_css_xpath_regex():
    cfg = Config.from_dict({
        "seeds": ["https://example.com"],
        "extract_mode": "both",
        "rules": [{
            "name": "page", "url_pattern": "/p$",
            "fields": {
                "heading": {"selector": "h1"},
                "links": {"selector": "a", "many": True, "limit": 3},
                "h1_xpath": {"xpath": "//h1/text()"},
                "word": {"regex": r"(第一段正文)"},
            },
        }],
    })
    item = Extractor(cfg).extract(_response()).item
    assert item["rules"]["page"]["heading"] == "主标题"
    assert item["rules"]["page"]["links"][0] == "A"
    assert item["rules"]["page"]["h1_xpath"] == "主标题"
    assert item["rules"]["page"]["word"] == "第一段正文"


def test_json_and_sitemap():
    cfg = Config.from_dict({"seeds": ["https://example.com"], "follow_external": True})
    ex = Extractor(cfg)
    json_resp = _response(
        b'{"count":2,"items":[{"title":"a","url":"/api/a"},{"title":"b","url":"/api/b"}]}',
        "application/json", "https://example.com/api/list",
    )
    result = ex.extract(json_resp)
    assert result.item["json"]["count"] == 2
    assert "https://example.com/api/a" in [r.url for r in result.links]

    sm = _response(
        b'<?xml version="1.0"?><urlset><url><loc>https://example.com/x</loc></url></urlset>',
        "application/xml", "https://example.com/sitemap.xml",
    )
    result = ex.extract(sm)
    assert result.item["xml_root"] == "urlset"
    assert "https://example.com/x" in [r.url for r in result.links]


def test_should_follow_depth_and_domain():
    cfg = Config.from_dict({"seeds": ["https://example.com"], "max_depth": 2})
    ex = Extractor(cfg)
    assert ex.should_follow("https://example.com/a", 2)[0]
    assert not ex.should_follow("https://example.com/a", 3)[0]
    assert not ex.should_follow("https://other.com/a", 1)[0]
    assert not ex.should_follow("https://example.com/admin/x", 1)[0]
