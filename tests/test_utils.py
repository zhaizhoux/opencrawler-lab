from opencrawler.utils import (
    decode_body,
    extension_of,
    host_of,
    normalize_url,
    registrable_match,
    resolve_url,
    sha256_text,
)


def test_normalize_url_basic():
    assert normalize_url("HTTPS://Example.COM:443/a/./b/../c/?utm_source=x&b=2&a=1#frag") == \
        "https://example.com/a/c/?a=1&b=2"
    assert normalize_url("http://example.com:80") == "http://example.com/"
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("mailto:a@b.com") is None
    assert normalize_url("not a url") is None


def test_resolve_and_host():
    assert resolve_url("https://a.com/x/y", "../z") == "https://a.com/z"
    assert resolve_url("https://a.com/x/y", "https://b.com/p") == "https://b.com/p"
    assert resolve_url("https://a.com/", "#frag") is None
    assert host_of("https://Sub.Example.com:8080/p") == "sub.example.com"


def test_domain_and_extension():
    assert registrable_match("blog.example.com", "example.com")
    assert not registrable_match("evil-example.com", "example.com")
    assert extension_of("https://a.com/p/image.JPG") == ".jpg"


def test_decode_and_hash():
    assert decode_body("<html>中文</html>".encode("gb18030"), "text/html; charset=gb18030") == "<html>中文</html>"
    assert "中文" in decode_body(b"\xef\xbb\xbf<html>\xe4\xb8\xad\xe6\x96\x87</html>", "text/html")
    assert len(sha256_text("abc")) == 64
