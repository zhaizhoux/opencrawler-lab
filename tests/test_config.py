import json

import pytest

from opencrawler.config import Config, ConfigError


def test_defaults_and_domain_inference():
    cfg = Config.from_dict({"seeds": ["https://news.example.com/a", "https://example.com/b"]})
    assert cfg.allowed_domains == ["example.com", "news.example.com"]
    assert cfg.respect_robots is True
    assert cfg.concurrency == 32
    assert cfg.state_file.endswith("state.sqlite3")


def test_unknown_key_rejected():
    with pytest.raises(ConfigError):
        Config.from_dict({"concurrrency": 10})


def test_invalid_values_rejected():
    with pytest.raises(ConfigError):
        Config.from_dict({"extract_mode": "stealth"})
    with pytest.raises(ConfigError):
        Config.from_dict({"storage": "mongodb"})
    with pytest.raises(ConfigError):
        Config.from_dict({"concurrency": 0})
    with pytest.raises(ConfigError):
        Config.from_dict({"rules": [{"name": "x", "url_pattern": ".*"}]})


def test_yaml_json_toml_roundtrip(tmp_path):
    data = {"seeds": ["https://example.com"], "max_pages": 7, "concurrency": 3}
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    cfg = Config.from_file(p, max_pages=9)
    assert cfg.max_pages == 9 and cfg.concurrency == 3

    y = tmp_path / "c.yaml"
    y.write_text("seeds:\n  - https://example.com\nmax_pages: 4\n", encoding="utf-8")
    assert Config.from_file(y).max_pages == 4

    t = tmp_path / "c.toml"
    t.write_text('seeds = ["https://example.com"]\nmax_pages = 6\n', encoding="utf-8")
    assert Config.from_file(t).max_pages == 6


def test_override_ignores_none():
    cfg = Config.from_dict({"seeds": ["https://example.com"]}, max_pages=None, concurrency=5)
    assert cfg.concurrency == 5 and cfg.max_pages == 1_000
