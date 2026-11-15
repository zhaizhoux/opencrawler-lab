"""配置加载与校验：支持 JSON / YAML / TOML 与命令行覆盖。"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, fields

try:  # Python 3.11+ 自带；3.10 可选安装 tomli
    import tomllib
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]
from pathlib import Path
from typing import Any

from .utils import DEFAULT_SKIP_EXTENSIONS, host_of

DEFAULT_USER_AGENT = (
    "OpenCrawlerLab/0.1 (+educational crawler; contact: set config.user_agent)"
)

DEFAULTS: dict[str, Any] = {
    # ---- 起点与范围 ----
    "seeds": [],
    "allowed_domains": [],              # 为空时自动取种子的域名
    "include_subdomains": True,
    "follow_external": False,
    "allow_url_patterns": [],
    "deny_url_patterns": [
        r"/(admin|wp-admin|administrator|login|logout|signin|signup|auth|account|cart|checkout|private|internal)(/|$)",
        r"[?&](token|api[_-]?key|password|secret)=",
    ],
    "skip_extensions": sorted(DEFAULT_SKIP_EXTENSIONS),
    "respect_nofollow": True,
    "follow_sitemaps": True,
    "follow_feeds": False,
    # ---- 合规（默认最保守）----
    "respect_robots": True,
    "robots_cache_ttl": 3600,
    "robots_on_error": "deny",         # deny | allow：robots 获取失败时的策略
    "obey_crawl_delay": True,
    "user_agent": DEFAULT_USER_AGENT,
    "default_delay_ms": 500,
    "per_domain_delay_ms": {},
    "per_domain_rps": 2.0,
    # ---- 并发与稳定性 ----
    "concurrency": 32,
    "adaptive_concurrency": True,     # 按成功率与 p95 延迟自动收敛/试探并发
    "adaptive_target_latency_ms": 1200,
    "per_domain_concurrency": 4,
    "request_timeout": 20.0,
    "connect_timeout": 5.0,
    "retries": 2,
    "backoff_base": 0.8,
    "max_content_length": 5_000_000,
    "max_depth": 5,
    "max_pages": 1_000,
    "max_bytes": 512 * 1024 * 1024,
    "time_budget_seconds": 0,          # 0 = 不限时（长时间运行）
    "conditional_requests": True,      # ETag / Last-Modified，减少重复传输
    "allowed_content_types": [
        "text/html", "application/xhtml+xml", "text/plain", "text/xml",
        "application/xml", "application/json", "application/ld+json",
        "application/rss+xml", "application/atom+xml", "text/css",
    ],
    # ---- 抽取 ----
    "extract_mode": "auto",            # auto | rules | both | raw
    "rules": [],
    "parsers": [],                     # ["pkg.module:callable", ...] 自定义解析器
    "render_js": False,                # 仅渲染公开页面，不用于绕过任何限制
    "text_min_length": 0,
    # ---- 存储与扩展 ----
    "storage": "jsonl",                # jsonl | sqlite | none
    "dedupe_content": True,            # 基于响应体哈希去掉镜像/重复页面
    "output_dir": "./output",
    "state_file": "",                  # 为空时 = output_dir/state.sqlite3
    "save_raw": False,
    "pipelines": [],                   # ["pkg.module:callable", ...]
    "middlewares": [],                 # ["pkg.module:callable", ...]
    "checkpoint_interval": 10.0,
    "metrics_interval": 15.0,
    "log_level": "INFO",
    "proxy": None,
    "extra_headers": {},
    "dry_run": False,
}

_MODES = {"auto", "rules", "both", "raw"}
_STORAGES = {"jsonl", "sqlite", "none"}


class ConfigError(ValueError):
    """配置有误。"""


@dataclass(slots=True)
class Config:
    seeds: list[str] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)
    include_subdomains: bool = True
    follow_external: bool = False
    allow_url_patterns: list[str] = field(default_factory=list)
    deny_url_patterns: list[str] = field(default_factory=list)
    skip_extensions: list[str] = field(default_factory=list)
    respect_nofollow: bool = True
    follow_sitemaps: bool = True
    follow_feeds: bool = False

    respect_robots: bool = True
    robots_cache_ttl: int = 3600
    robots_on_error: str = "deny"
    obey_crawl_delay: bool = True
    user_agent: str = DEFAULT_USER_AGENT
    default_delay_ms: int = 500
    per_domain_delay_ms: dict[str, int] = field(default_factory=dict)
    per_domain_rps: float = 2.0

    concurrency: int = 32
    adaptive_concurrency: bool = True
    adaptive_target_latency_ms: int = 1200
    per_domain_concurrency: int = 4
    request_timeout: float = 20.0
    connect_timeout: float = 5.0
    retries: int = 2
    backoff_base: float = 0.8
    max_content_length: int = 5_000_000
    max_depth: int = 5
    max_pages: int = 1_000
    max_bytes: int = 512 * 1024 * 1024
    time_budget_seconds: int = 0
    conditional_requests: bool = True
    allowed_content_types: list[str] = field(default_factory=list)

    extract_mode: str = "auto"
    rules: list[dict[str, Any]] = field(default_factory=list)
    parsers: list[str] = field(default_factory=list)
    render_js: bool = False
    text_min_length: int = 0

    storage: str = "jsonl"
    dedupe_content: bool = True
    output_dir: str = "./output"
    state_file: str = ""
    save_raw: bool = False
    pipelines: list[str] = field(default_factory=list)
    middlewares: list[str] = field(default_factory=list)
    checkpoint_interval: float = 10.0
    metrics_interval: float = 15.0
    log_level: str = "INFO"
    proxy: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False

    warnings: list[str] = field(default_factory=list)

    # ---------------- 构造 ----------------
    @classmethod
    def from_dict(cls, data: dict[str, Any] | None = None, **overrides: Any) -> "Config":
        merged = copy.deepcopy(DEFAULTS)
        if data:
            unknown = set(data) - set(DEFAULTS)
            if unknown:
                raise ConfigError(f"未知配置项: {', '.join(sorted(unknown))}")
            merged.update(data)
        clean_overrides = {k: v for k, v in overrides.items() if v is not None}
        unknown = set(clean_overrides) - set(DEFAULTS)
        if unknown:
            raise ConfigError(f"未知配置项: {', '.join(sorted(unknown))}")
        merged.update(clean_overrides)
        names = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in merged.items() if k in names})
        cfg.validate()
        return cfg

    @classmethod
    def from_file(cls, path: str | Path, **overrides: Any) -> "Config":
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"配置文件不存在: {p}")
        text = p.read_text(encoding="utf-8")
        suffix = p.suffix.lower()
        if suffix == ".json":
            data = json.loads(text)
        elif suffix in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError as exc:  # pragma: no cover
                raise ConfigError("读取 YAML 需要安装 PyYAML: pip install PyYAML") from exc
            data = yaml.safe_load(text) or {}
        elif suffix == ".toml":
            if tomllib is None:
                raise ConfigError("读取 TOML 需要 Python 3.11+ 或安装 tomli")
            data = tomllib.loads(text)
        else:
            raise ConfigError(f"不支持的配置文件格式: {suffix}")
        if not isinstance(data, dict):
            raise ConfigError("配置文件顶层必须是映射/对象")
        # 相对路径按配置文件所在目录解析
        for key in ("output_dir", "state_file"):
            if isinstance(data.get(key), str) and data[key] and not Path(data[key]).is_absolute():
                data[key] = str((p.parent / data[key]).resolve())
        return cls.from_dict(data, **overrides)

    def validate(self) -> None:
        if not isinstance(self.seeds, list) or any(not isinstance(s, str) for s in self.seeds):
            raise ConfigError("seeds 必须是字符串列表")
        if self.extract_mode not in _MODES:
            raise ConfigError(f"extract_mode 必须是 {sorted(_MODES)} 之一")
        if self.storage not in _STORAGES:
            raise ConfigError(f"storage 必须是 {sorted(_STORAGES)} 之一")
        if self.robots_on_error not in {"deny", "allow"}:
            raise ConfigError("robots_on_error 必须是 deny 或 allow")
        for key in ("concurrency", "per_domain_concurrency", "max_pages", "retries"):
            if getattr(self, key) < 1:
                raise ConfigError(f"{key} 必须 >= 1")
        if self.per_domain_concurrency > self.concurrency:
            self.per_domain_concurrency = self.concurrency
        if self.max_depth < 0:
            raise ConfigError("max_depth 必须 >= 0")
        if self.default_delay_ms < 0 or self.per_domain_rps <= 0:
            raise ConfigError("限速参数必须为非负值 / 正 RPS")
        if not isinstance(self.rules, list) or any(not isinstance(r, dict) for r in self.rules):
            raise ConfigError("rules 必须是对象列表")
        for key in ("pipelines", "middlewares", "parsers"):
            if not isinstance(getattr(self, key), list):
                raise ConfigError(f"{key} 必须是字符串列表")
        for rule in self.rules:
            for required in ("name", "url_pattern", "fields"):
                if required not in rule:
                    raise ConfigError(f"规则缺少必填字段 {required}: {rule}")
            if not isinstance(rule["fields"], dict):
                raise ConfigError(f"规则 {rule['name']} 的 fields 必须是对象")
        if not self.allowed_domains and self.seeds:
            self.allowed_domains = sorted({host_of(s) for s in self.seeds if host_of(s)})
        if not self.state_file:
            self.state_file = str((Path(self.output_dir) / "state.sqlite3").resolve())
        self.output_dir = str(Path(self.output_dir).resolve())
        self.state_file = str(Path(self.state_file).resolve())
        if not self.respect_robots:
            self.warnings.append("已关闭 robots.txt 合规检查，请仅在自己拥有或已获授权的站点使用")
        if self.render_js:
            self.warnings.append("render_js 为声明式扩展点，请自备 Playwright 并在自有站点使用")
        if self.follow_external:
            self.warnings.append("已开启跨域抓取，请确认目标站点允许并适当降低并发")

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "warnings"}
