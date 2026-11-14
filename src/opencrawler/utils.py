"""通用工具：URL 规范化、哈希、内容解码、匹配与格式化。

所有函数都不依赖第三方库，便于在受限环境中直接使用。
"""
from __future__ import annotations

import hashlib
import posixpath
import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

# 常见的纯跟踪参数：规范化时丢弃，避免同一页面产生无数重复 URL
TRACKING_PARAMS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "utm_id", "utm_name", "utm_reader", "utm_social", "gclid", "fbclid",
        "dclid", "msclkid", "igshid", "mc_cid", "mc_eid", "_ga", "spm",
        "from_source", "ref_src", "sharing", "share_token", "sessionid",
    }
)

# 默认不抓取的静态资源后缀（可通过配置覆盖）
DEFAULT_SKIP_EXTENSIONS = frozenset(
    {
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp",
        ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".webm",
        ".zip", ".rar", ".7z", ".gz", ".tar", ".bz2", ".exe", ".msi",
        ".dmg", ".apk", ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".css", ".js", ".map", ".iso", ".deb", ".rpm", ".bin",
    }
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_META_CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([\w\-]+)", re.I)


def normalize_url(url: str, *, drop_tracking: bool = True) -> str | None:
    """把 URL 规范化成可用于去重的形式；非法或不支持的 URL 返回 None。

    处理：协议/主机小写、去掉默认端口与 userinfo、路径归一化、去掉 fragment、
    过滤跟踪参数并排序 query、保留尾部斜杠。
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip().replace("\r", "").replace("\n", "")
    if not url or url.startswith(("mailto:", "javascript:", "data:", "tel:", "#")):
        return None
    if url.startswith("//"):
        url = "https:" + url
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            return None
        hostname = (parts.hostname or "").lower().rstrip(".")
        if not hostname:
            return None
        try:
            port = parts.port
        except ValueError:
            return None
    except ValueError:
        return None

    netloc = hostname
    if port and not (scheme == "http" and port == 80) and not (scheme == "https" and port == 443):
        netloc = f"{hostname}:{port}"

    raw_path = parts.path or "/"
    path = posixpath.normpath(raw_path)
    if raw_path.endswith("/") and not path.endswith("/"):
        path += "/"
    if not path.startswith("/"):
        path = "/" + path

    query = ""
    if parts.query:
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        if drop_tracking:
            pairs = [(k, v) for k, v in pairs if k.lower() not in TRACKING_PARAMS]
        pairs.sort()
        query = urlencode(pairs, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def resolve_url(base: str, href: str) -> str | None:
    """相对链接转绝对链接并规范化。"""
    if not href:
        return None
    href = href.strip()
    if href.startswith(("javascript:", "mailto:", "data:", "tel:", "#")):
        return None
    try:
        return normalize_url(urljoin(base, href))
    except (ValueError, TypeError):
        return None


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def registrable_match(host: str, domain: str, *, include_subdomains: bool = True) -> bool:
    """轻量域名归属判断（不依赖公共后缀列表，避免额外依赖）。"""
    host = host.lower().rstrip(".")
    domain = domain.lower().lstrip(".").rstrip(".")
    if not domain:
        return False
    return host == domain or (include_subdomains and host.endswith("." + domain))


def extension_of(url: str) -> str:
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return ""
    name = path.rsplit("/", 1)[-1]
    return ("." + name.rsplit(".", 1)[-1]) if "." in name else ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def decode_body(body: bytes, content_type: str = "", *, default: str = "utf-8") -> str:
    """按 HTTP Content-Type / BOM / HTML meta 推断编码，失败时容错解码。"""
    if body.startswith(b"\xef\xbb\xbf"):
        return body[3:].decode("utf-8", "replace")
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        return body.decode("utf-16", "replace")
    candidates: list[str] = []
    match = re.search(r"charset\s*=\s*[\"']?\s*([\w\-]+)", content_type or "", re.I)
    if match:
        candidates.append(match.group(1))
    if body[:4096].lower().startswith(b"<?xml") or b"<html" in body[:4096].lower():
        meta = _META_CHARSET.search(body[:4096])
        if meta:
            candidates.append(meta.group(1).decode("ascii", "ignore"))
    candidates.extend(["utf-8", default, "gb18030", "latin-1"])
    seen: set[str] = set()
    for enc in candidates:
        key = enc.lower()
        if not enc or key in seen:
            continue
        seen.add(key)
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def matches_any(value: str, patterns) -> bool:
    """正则或字面子串匹配（用于 URL 白/黑名单与规则匹配）。"""
    for pattern in patterns or []:
        try:
            if re.search(pattern, value):
                return True
        except re.error:
            if pattern in value:
                return True
    return False


def safe_filename(name: str, *, max_len: int = 120) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("_")
    return (cleaned or "item")[:max_len]


def human_bytes(num: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(num) < 1024.0:
            return f"{num:.1f}{unit}"
        num /= 1024.0
    return f"{num:.1f}PiB"


def now_ms() -> int:
    return int(time.time() * 1000)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
