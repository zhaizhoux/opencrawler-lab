"""共用桌面前端的静态契约测试（零前端依赖）。

三仓库的 desktop/web/ 三个文件要求字节级一致；这里守住最容易漂移的两类问题：
app.js 引用了 HTML 中不存在的 id，以及指标卡缺少某个 data-k 键。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "desktop" / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "app.css").read_text(encoding="utf-8")


def test_assets_reference_each_other():
    assert 'href="/app.css"' in HTML
    assert 'src="/app.js"' in HTML
    assert '<html lang="zh-CN"' in HTML


def test_every_js_id_exists_in_html():
    html_ids = set(re.findall(r'\bid="([\w-]+)"', HTML))
    js_ids = set(re.findall(r"\$\('([\w-]+)'\)", JS))
    missing = sorted(js_ids - html_ids)
    assert not missing, f"app.js 引用了不存在的元素 id: {missing}"


def test_all_metric_keys_present():
    keys = set(re.findall(r'data-k="([\w-]+)"', HTML))
    # 只匹配指标卡里的 set('key', ...)，排除 params.set('q', ...) 之类的方法调用
    used = set(re.findall(r"(?<![\w.])set\('([\w-]+)',", JS))
    assert not used - keys, f"指标卡缺少 data-k: {sorted(used - keys)}"
    assert len(keys) == 12, f"应有 12 个指标卡，实际 {len(keys)}"


def test_dark_and_light_themes_defined():
    assert ':root[data-theme="dark"]' in CSS
    assert ':root[data-theme="light"]' in CSS
    assert "--accent:" in CSS


def test_no_external_dependencies():
    # 桌面窗口必须能离线运行，不能引入 CDN / 框架。
    assert "cdn." not in HTML.lower()
    assert "https://" not in CSS
    assert "import " not in JS or "from '" not in JS
    assert "EventSource" in JS and "fetch(" in JS


def test_compliance_and_version_fallback():
    assert "robots.txt" in HTML
    assert "0.3.0" in JS
    assert "/api/info" in JS
