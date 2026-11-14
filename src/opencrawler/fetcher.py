"""异步 HTTP 下载器：连接池、超时、体长限制、条件请求、指数退避重试。"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

import aiohttp

from .config import Config
from .frontier import Frontier
from .models import Request, Response
from .utils import decode_body


@dataclass(slots=True)
class FetchResult:
    response: Response | None = None
    error: str = ""
    skipped: str = ""          # 非空表示成功取得响应但按策略跳过解析
    not_modified: bool = False


class Fetcher:
    def __init__(self, config: Config, frontier: Frontier, logger: logging.Logger | None = None) -> None:
        self.cfg = config
        self.frontier = frontier
        self.log = logger or logging.getLogger("opencrawler.fetcher")
        self.session: aiohttp.ClientSession | None = None
        self._connector: aiohttp.TCPConnector | None = None

    async def __aenter__(self) -> "Fetcher":
        self._connector = aiohttp.TCPConnector(
            limit=self.cfg.concurrency,
            limit_per_host=self.cfg.per_domain_concurrency,
            ttl_dns_cache=300,
            force_close=False,
        )
        timeout = aiohttp.ClientTimeout(
            total=self.cfg.request_timeout, connect=self.cfg.connect_timeout, sock_read=self.cfg.request_timeout
        )
        self.session = aiohttp.ClientSession(
            connector=self._connector,
            timeout=timeout,
            headers={"User-Agent": self.cfg.user_agent, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            trust_env=False,
            auto_decompress=True,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self.session:
            await self.session.close()
        if self._connector:
            await self._connector.close()

    def _headers(self, request: Request) -> dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.5",
            **self.cfg.extra_headers,
            **request.headers,
        }
        if self.cfg.conditional_requests:
            validators = self.frontier.get_validators(request.url)
            if validators.get("etag"):
                headers["If-None-Match"] = validators["etag"]
            if validators.get("last_modified"):
                headers["If-Modified-Since"] = validators["last_modified"]
        return headers

    def _mime_allowed(self, mime: str) -> bool:
        allowed = [a.lower() for a in self.cfg.allowed_content_types]
        if not allowed or not mime:
            return True
        return any(
            mime == rule or (rule.endswith("/*") and mime.startswith(rule[:-1])) or rule == "*"
            for rule in allowed
        )

    async def _once(self, request: Request) -> FetchResult:
        assert self.session is not None
        started = asyncio.get_running_loop().time()
        kwargs: dict = {
            "headers": self._headers(request),
            "allow_redirects": True,
            "max_redirects": 5,
        }
        if self.cfg.proxy:
            kwargs["proxy"] = self.cfg.proxy
        try:
            response = await self.session.get(request.url, **kwargs)
        except TypeError:  # 兼容不带 proxy 参数的 aiohttp 版本
            kwargs.pop("proxy", None)
            response = await self.session.get(request.url, **kwargs)

        async with response:
            elapsed = int((asyncio.get_running_loop().time() - started) * 1000)
            headers = {k.lower(): v for k, v in response.headers.items()}
            mime = headers.get("content-type", "").split(";")[0].strip().lower()
            status = response.status

            if status == 304 and self.cfg.conditional_requests:
                return FetchResult(not_modified=True)
            if status >= 400:
                return FetchResult(
                    Response(request, status, str(response.url), headers, b"", elapsed, mime),
                    error=f"HTTP {status}",
                )

            declared = headers.get("content-length")
            cap = self.cfg.max_content_length
            if declared and declared.isdigit() and int(declared) > cap:
                return FetchResult(
                    Response(request, status, str(response.url), headers, b"", elapsed, mime),
                    skipped=f"响应体 {declared} 字节超过上限 {cap}",
                )
            if not self._mime_allowed(mime):
                return FetchResult(
                    Response(request, status, str(response.url), headers, b"", elapsed, mime),
                    skipped=f"内容类型 {mime or '未知'} 不在允许列表",
                )

            chunks: list[bytes] = []
            total = 0
            truncated = False
            async for chunk in response.content.iter_chunked(65536):
                total += len(chunk)
                if total > cap:
                    chunks.append(chunk[: max(0, cap - (total - len(chunk)))])
                    truncated = True
                    response.release()
                    break
                chunks.append(chunk)
            body = b"".join(chunks)
            if truncated:
                headers["x-opencrawler-truncated"] = "1"
            resp = Response(request, status, str(response.url), headers, body, elapsed, mime)
            return FetchResult(resp)

    async def fetch(self, request: Request) -> FetchResult:
        last_error = ""
        for attempt in range(self.cfg.retries + 1):
            try:
                result = await self._once(request)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                result = FetchResult(error=last_error)
            else:
                if result.not_modified or result.skipped:
                    return result
                if result.response and result.response.ok:
                    headers = result.response.headers
                    self.frontier.set_validators(
                        request.url, headers.get("etag", ""), headers.get("last-modified", "")
                    )
                    return result
                last_error = result.error or "未知错误"

            retryable = False
            if result.response and result.response.status in {408, 425, 429, 500, 502, 503, 504}:
                retryable = True
            elif not result.response:
                retryable = True
            if not retryable or attempt >= self.cfg.retries:
                break
            wait = self.cfg.backoff_base * (2 ** attempt) + random.uniform(0, 0.3)
            if result.response:
                retry_after = result.response.headers.get("retry-after", "")
                if retry_after.isdigit():
                    wait = max(wait, min(float(retry_after), 60.0))
                if result.response.status == 429:
                    self._penalize(request.url, wait)
            self.log.debug("重试 %s (第 %d 次, 等待 %.2fs): %s", request.url, attempt + 1, wait, last_error)
            await asyncio.sleep(wait)
        return FetchResult(error=last_error or "请求失败")

    def _penalize(self, url: str, seconds: float) -> None:
        # 由 Engine 注入，避免 Fetcher 与限速器强耦合
        if self._penalty_hook:
            self._penalty_hook(url, seconds)

    _penalty_hook = None

    async def get_text(self, url: str) -> tuple[int, str]:
        """供 robots.txt / sitemap 等内部用途读取小文本。"""
        assert self.session is not None
        try:
            async with self.session.get(url, headers={"User-Agent": self.cfg.user_agent}) as resp:
                body = await resp.read()
                return resp.status, decode_body(body, resp.headers.get("Content-Type", ""))
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            self.log.debug("读取 %s 失败: %s", url, exc)
            return 0, ""
