"""站点自适应抽取器：HTML / JSON / XML(Sitemap/RSS) / 纯文本 + 可配置规则 + 插件。

设计目标：不改代码就能适配绝大多数公开网站 —— 自动模式拿通用元信息，
规则模式用 CSS/XPath/JSONPath/正则拿结构化字段，插件模式处理特殊站点。
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any

from .config import Config
from .models import ExtractResult, Request, Response
from .utils import (
    extension_of,
    host_of,
    matches_any,
    registrable_match,
    resolve_url,
    sha256_bytes,
)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:  # pragma: no cover - 无依赖降级
    BeautifulSoup = None  # type: ignore[assignment]
    HAS_BS4 = False

try:
    from lxml import html as lxml_html
    HAS_LXML = True
except ImportError:  # pragma: no cover
    lxml_html = None  # type: ignore[assignment]
    HAS_LXML = False

_SKIP_TEXT_TAGS = ("script", "style", "noscript", "nav", "footer", "header", "form", "aside", "svg", "iframe")
_REFRESH = re.compile(r"^\s*\d+\s*;\s*url\s*=\s*['\"]?(.+?)['\"]?\s*$", re.I)


class _MiniHTMLParser(HTMLParser):
    """无 bs4 时的最小降级解析：标题、元信息、链接、正文。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[tuple[str, bool]] = []
        self.metas: dict[str, str] = {}
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and a.get("href"):
            rel = (a.get("rel") or "").lower()
            self.links.append((a["href"], "nofollow" in rel))
        if tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key:
                self.metas[key] = a.get("content", "")

    def handle_endtag(self, tag):
        if tag in _SKIP_TEXT_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if not self._skip_depth and data.strip():
            self.text_parts.append(data)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _json_path(data: Any, path: str) -> Any:
    """轻量 JSON 路径：a.b.0.c，支持 $ 前缀与 .. 通配一层。"""
    path = path.lstrip("$").lstrip(".")
    if ".." in path:
        head, tail = path.split("..", 1)
        base = _json_path(data, head) if head else data
        found: list[Any] = []
        stack = [base]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == tail.split(".")[0]:
                        found.append(_json_path(value, tail) if "." in tail else value)
                    stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
        return found
    node = data
    for part in (p for p in path.split(".") if p):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
        if node is None:
            return None
    return node


def _transform(value: Any, transforms: list[str] | str, base_url: str) -> Any:
    steps = [transforms] if isinstance(transforms, str) else list(transforms or [])
    for step in steps:
        if value is None:
            break
        if step == "strip":
            value = re.sub(r"\s+", " ", str(value)).strip()
        elif step == "lower":
            value = str(value).lower()
        elif step == "upper":
            value = str(value).upper()
        elif step == "int":
            try:
                value = int(re.sub(r"[^\d\-]", "", str(value)) or 0)
            except ValueError:
                value = 0
        elif step == "float":
            try:
                value = float(re.sub(r"[^\d.\-]", "", str(value)) or 0)
            except ValueError:
                value = 0.0
        elif step == "join":
            value = " ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        elif step == "url":
            value = resolve_url(base_url, str(value)) or value
        elif step == "json":
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                pass
    return value


class Extractor:
    def __init__(self, config: Config, logger: logging.Logger | None = None) -> None:
        self.cfg = config
        self.log = logger or logging.getLogger("opencrawler.extractor")
        self.parsers = []
        for spec in getattr(config, "parsers", []):
            from .plugins import load_callable
            try:
                self.parsers.append(load_callable(spec))
            except (ImportError, AttributeError, ValueError) as exc:
                self.log.warning("加载自定义解析器 %s 失败: %s", spec, exc)
        if config.rules and not HAS_BS4:
            self.log.warning("规则抽取需要 beautifulsoup4，当前仅可用自动模式")

    # ---------------- 入口 ----------------
    def extract(self, response: Response) -> ExtractResult:
        mime = (response.content_type or "").lower()
        text = response.text
        content_hash = sha256_bytes(response.body)
        base = response.final_url or response.request.url

        for parser in self.parsers:
            try:
                custom = parser(response)
            except Exception as exc:  # noqa: BLE001 - 用户插件需隔离
                self.log.warning("自定义解析插件异常: %s", exc)
                continue
            if isinstance(custom, ExtractResult):
                return custom
            if isinstance(custom, dict) and custom:
                result = ExtractResult(item=custom, content_hash=content_hash)
                result.links = self.discover_links(
                    base, [], follow_meta=True, mode="custom", parent_depth=response.request.depth
                )
                return result

        item: dict[str, Any] = {
            "url": response.request.url,
            "final_url": response.final_url,
            "status": response.status,
            "content_type": mime,
            "size": response.size,
            "elapsed_ms": response.elapsed_ms,
            "content_hash": content_hash,
            "kind": response.request.kind,
        }
        raw_links: list[str] = []
        follow_meta = True
        body_text = ""

        if "json" in mime or text.lstrip().startswith(("{", "[")):
            item.update(self._parse_json(text))
            raw_links = self._json_links(item.get("json"))
        elif "xml" in mime or text.lstrip().startswith("<?xml") or "<urlset" in text[:512] or "<rss" in text[:512]:
            parsed = self._parse_xml(text)
            item.update(parsed["item"])
            raw_links = parsed["links"]
        elif "html" in mime or "<html" in text[:2048].lower() or "<body" in text[:2048].lower():
            html_result = self._parse_html(text, response)
            item.update(html_result["item"])
            raw_links = html_result["links"]
            follow_meta = html_result["follow_meta"]
            body_text = html_result["text"]
        else:
            item["text"] = text[: self.cfg.max_content_length]

        item["text_length"] = len(body_text) if body_text else item.get("text_length", 0)

        if self.cfg.extract_mode in {"rules", "both", "auto"}:
            rules_result = self.apply_rules(response, text)
            if rules_result:
                item["rules"] = rules_result
        if self.cfg.extract_mode == "raw":
            item["raw_text"] = text[: self.cfg.max_content_length]

        result = ExtractResult(item=item, content_hash=content_hash)
        result.links = self.discover_links(
            base, raw_links, follow_meta=follow_meta, parent_depth=response.request.depth
        )
        if self.cfg.text_min_length and body_text and len(body_text) < self.cfg.text_min_length:
            result.skip, result.reason = True, "正文长度低于阈值"
        return result

    # ---------------- HTML ----------------
    def _parse_html(self, text: str, response: Response) -> dict[str, Any]:
        base = response.final_url or response.request.url
        metas: dict[str, str] = {}
        links: list[str] = []
        follow_meta = True
        title = h1 = lang = canonical = ""
        headings: list[str] = []
        jsonld: list[Any] = []

        if HAS_BS4:
            soup = BeautifulSoup(text, "lxml" if HAS_LXML else "html.parser")
            for meta in soup.find_all("meta"):
                key = (meta.get("name") or meta.get("property") or meta.get("itemprop") or "").lower()
                if key:
                    metas[key] = meta.get("content", "")
            robots_meta = (metas.get("robots") or metas.get("googlebot") or "").lower()
            follow_meta = not ("nofollow" in robots_meta or "none" in robots_meta)
            noindex = "noindex" in robots_meta
            if soup.title and soup.title.string:
                title = soup.title.get_text(" ", strip=True)
            html_tag = soup.find("html")
            lang = (html_tag.get("lang") if html_tag else "") or ""
            canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in v)
            if canonical_tag and canonical_tag.get("href"):
                canonical = resolve_url(base, canonical_tag["href"]) or ""
            first_h1 = soup.find("h1")
            h1 = first_h1.get_text(" ", strip=True) if first_h1 else ""
            headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])][:20]
            for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
                try:
                    jsonld.append(json.loads(script.string or script.get_text()))
                except (ValueError, TypeError):
                    continue

            for tag in soup.find_all(["a", "area", "link"], href=True):
                rel = " ".join(tag.get("rel") or []).lower() if isinstance(tag.get("rel"), list) else str(tag.get("rel") or "").lower()
                if self.cfg.respect_nofollow and "nofollow" in rel:
                    continue
                if tag.name == "link" and "alternate" not in rel and "next" not in rel and "prev" not in rel:
                    continue
                links.append(tag["href"])
            for tag in soup.find_all("meta", attrs={"http-equiv": re.compile("refresh", re.I)}):
                match = _REFRESH.match(tag.get("content", ""))
                if match:
                    links.append(match.group(1))
            for tag in soup(_SKIP_TEXT_TAGS):
                tag.decompose()
            body = soup.body or soup
            body_text = re.sub(r"\s+", " ", body.get_text(" ", strip=True)).strip()
        else:  # 降级路径
            mini = _MiniHTMLParser()
            mini.feed(text)
            metas, links = mini.metas, [href for href, nf in mini.links if not (nf and self.cfg.respect_nofollow)]
            title = re.sub(r"\s+", " ", " ".join(mini.title_parts)).strip()
            body_text = re.sub(r"\s+", " ", " ".join(mini.text_parts)).strip()
            noindex = "noindex" in (metas.get("robots") or "").lower()
            follow_meta = "nofollow" not in (metas.get("robots") or "").lower()

        og = {k[3:]: v for k, v in metas.items() if k.startswith("og:")}
        return {
            "item": {
                "title": title or og.get("title") or "",
                "description": metas.get("description") or metas.get("og:description", ""),
                "canonical": canonical,
                "lang": lang,
                "h1": h1,
                "headings": headings,
                "text": body_text[: self.cfg.max_content_length],
                "text_length": len(body_text),
                "word_count": len(body_text.split()),
                "meta": metas,
                "open_graph": og,
                "json_ld": jsonld[:10],
                "noindex": noindex,
                "author": metas.get("author", ""),
                "published_time": metas.get("article:published_time") or metas.get("date", ""),
            },
            "links": links,
            "text": body_text,
            "follow_meta": follow_meta,
        }

    # ---------------- JSON ----------------
    def _parse_json(self, text: str) -> dict[str, Any]:
        try:
            data = json.loads(text)
        except ValueError:
            return {"text": text[: self.cfg.max_content_length], "json_error": True}
        preview = data
        if isinstance(data, dict):
            keys = list(data)[:20]
            preview = {k: data[k] for k in keys}
        elif isinstance(data, list):
            preview = data[:20]
        return {"json": preview, "json_type": type(data).__name__}

    def _json_links(self, data: Any, *, _depth: int = 0, _found: list[str] | None = None) -> list[str]:
        found = _found if _found is not None else []
        if len(found) >= 200 or _depth > 8:
            return found
        if isinstance(data, str):
            if data.startswith(("http://", "https://", "/")):
                found.append(data)
        elif isinstance(data, dict):
            for key, value in data.items():
                if key.lower() in {"url", "href", "link", "next", "prev", "permalink", "loc"} or isinstance(value, (dict, list)):
                    self._json_links(value, _depth=_depth + 1, _found=found)
        elif isinstance(data, list):
            for value in data[:100]:
                self._json_links(value, _depth=_depth + 1, _found=found)
        return found

    # ---------------- XML / Sitemap / RSS ----------------
    def _parse_xml(self, text: str) -> dict[str, Any]:
        links: list[str] = []
        entries: list[dict[str, str]] = []
        root_name = ""
        try:
            root = ET.fromstring(text)
            root_name = _localname(root.tag)
            for element in root.iter():
                name = _localname(element.tag)
                if name in {"loc", "link", "guid", "url"} and (element.text or "").strip():
                    value = element.text.strip()
                    if value.startswith(("http://", "https://")):
                        links.append(value)
                if name in {"item", "entry", "url"}:
                    entry: dict[str, str] = {}
                    for child in element:
                        key = _localname(child.tag)
                        if key in {"title", "link", "loc", "pubdate", "published", "updated", "description", "lastmod", "changefreq", "priority"}:
                            entry[key] = (child.text or child.get("href") or "").strip()
                    if entry:
                        entries.append(entry)
        except ET.ParseError as exc:
            return {"item": {"xml_error": str(exc), "text": text[:2000]}, "links": []}
        return {
            "item": {
                "xml_root": root_name,
                "xml_entries": entries[:100],
                "xml_entry_count": len(entries),
                "text": text[:2000],
            },
            "links": links[:500],
        }

    # ---------------- 规则 ----------------
    def apply_rules(self, response: Response, text: str) -> dict[str, dict[str, Any]]:
        if not self.cfg.rules:
            return {}
        soup = None
        lxml_tree = None
        json_data = None
        if HAS_BS4:
            soup = BeautifulSoup(text, "lxml" if HAS_LXML else "html.parser")
        if HAS_LXML and ("html" in response.content_type or "<html" in text[:2048].lower()):
            try:
                lxml_tree = lxml_html.fromstring(text)
            except Exception:  # noqa: BLE001
                lxml_tree = None
        if "json" in response.content_type:
            try:
                json_data = json.loads(text)
            except ValueError:
                json_data = None

        results: dict[str, dict[str, Any]] = {}
        for rule in self.cfg.rules:
            if not re.search(rule["url_pattern"], response.final_url or response.request.url, re.I):
                continue
            fields: dict[str, Any] = {}
            for name, spec in rule["fields"].items():
                if not isinstance(spec, dict):
                    spec = {"selector": str(spec)}
                fields[name] = self._field(
                    spec, soup=soup, lxml_tree=lxml_tree, json_data=json_data,
                    text=text, base=response.final_url or response.request.url,
                )
            results[rule["name"]] = fields
        return results

    def _field(self, spec: dict[str, Any], *, soup, lxml_tree, json_data, text: str, base: str) -> Any:
        many = bool(spec.get("many"))
        values: list[Any] = []
        if spec.get("const") is not None:
            values = [spec["const"]]
        elif spec.get("json_path") and json_data is not None:
            got = _json_path(json_data, spec["json_path"])
            values = got if isinstance(got, list) and many else [got]
        elif spec.get("xpath") and lxml_tree is not None:
            try:
                nodes = lxml_tree.xpath(spec["xpath"])
                for node in nodes:
                    if isinstance(node, str):
                        values.append(node)
                    else:
                        attr = spec.get("attr")
                        values.append(node.get(attr) if attr else node.text_content().strip())
            except Exception as exc:  # noqa: BLE001
                self.log.debug("XPath %s 执行失败: %s", spec["xpath"], exc)
        elif spec.get("selector") and soup is not None:
            for node in soup.select(spec["selector"]):
                attr = spec.get("attr")
                values.append(node.get(attr) if attr else node.get_text(" ", strip=True))
        elif spec.get("regex"):
            values = re.findall(spec["regex"], text, re.I | re.S)

        values = [_transform(v, spec.get("transform", "strip"), base) for v in values if v is not None]
        if spec.get("join"):
            return str(spec["join"]).join(str(v) for v in values)
        if many:
            return values[: int(spec.get("limit", 100))]
        return values[0] if values else spec.get("default")

    # ---------------- 链接发现 ----------------
    def should_follow(self, url: str, depth: int, *, kind: str = "page") -> tuple[bool, str]:
        if not url:
            return False, "空 URL"
        if depth > self.cfg.max_depth:
            return False, "超出深度限制"
        if matches_any(url, self.cfg.deny_url_patterns):
            return False, "命中 URL 黑名单"
        if self.cfg.allow_url_patterns and not matches_any(url, self.cfg.allow_url_patterns):
            return False, "未命中 URL 白名单"
        if kind != "sitemap" and extension_of(url) in set(self.cfg.skip_extensions):
            return False, "静态资源后缀"
        if not self.cfg.follow_external:
            host = host_of(url)
            if not any(
                registrable_match(host, domain, include_subdomains=self.cfg.include_subdomains)
                for domain in self.cfg.allowed_domains
            ):
                return False, "超出允许域名"
        return True, ""

    def discover_links(
        self, base: str, hrefs: list[str], *, follow_meta: bool = True,
        mode: str = "auto", parent_depth: int = 0,
    ) -> list[Request]:
        if self.cfg.extract_mode == "raw" and mode != "custom":
            return []
        if not follow_meta and self.cfg.respect_nofollow:
            # meta nofollow 仍允许解析，但链接不再向外扩展
            return []
        seen: set[str] = set()
        out: list[Request] = []
        depth = parent_depth + 1
        for href in hrefs:
            url = resolve_url(base, href)
            if not url or url in seen:
                continue
            seen.add(url)
            kind = "sitemap" if url.endswith((".xml", ".xml.gz")) and "sitemap" in url.lower() else "page"
            if kind == "sitemap" and not self.cfg.follow_sitemaps:
                continue
            ok, _ = self.should_follow(url, depth, kind=kind)
            if ok:
                priority = 10 if kind == "sitemap" else 0
                out.append(Request(url=url, depth=depth, kind=kind, priority=priority))
        return out
