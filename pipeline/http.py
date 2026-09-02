"""Single polite HTTP client: retries with backoff, honours Retry-After, per-host min interval."""

from __future__ import annotations

import logging
import time

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from .config import settings

log = logging.getLogger(__name__)

_last_call: dict[str, float] = {}


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


class Client:
    def __init__(self, min_interval: float = 1.0, timeout: float = 180.0):
        self.min_interval = min_interval
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": settings().reddit_user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )

    def _throttle(self, host: str) -> None:
        wait = _last_call.get(host, 0) + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()

    @retry(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(6),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def request(self, method: str, url: str, **kw) -> httpx.Response:
        host = httpx.URL(url).host
        self._throttle(host)
        resp = self._client.request(method, url, **kw)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 30))
            log.warning("429 from %s, sleeping %ss", host, retry_after)
            time.sleep(retry_after)
        resp.raise_for_status()
        return resp

    def get(self, url: str, **kw) -> httpx.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> httpx.Response:
        return self.request("POST", url, **kw)
