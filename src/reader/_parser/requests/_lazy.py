"""httpx-dependent classes. Imported lazily to keep urllib.request out of startup."""

from __future__ import annotations

import logging
from collections.abc import Callable
from collections.abc import Generator

import httpx


class UAFallbackAuth(httpx.Auth):
    """Auth handler that retries 403 responses with a fallback User-Agent."""

    def __init__(self, fallback_ua: str | Callable[[], str]):
        """Initialize UA fallback auth.

        Args:
            fallback_ua: The fallback User-Agent string, or a callable that
                returns the string (called lazily on first 403 response).
        """
        self._fallback_ua = fallback_ua

    @property
    def fallback_ua(self) -> str:
        if callable(self._fallback_ua):
            return self._fallback_ua()
        return self._fallback_ua

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        """Handle request/response with declarative retry logic."""
        response = yield request

        if response.status_code == 403:
            current_ua = request.headers.get("User-Agent", "")
            fallback_prefix = self.fallback_ua.partition(" ")[0]

            if current_ua and not current_ua.startswith(fallback_prefix):
                log = logging.getLogger("reader.plugins.ua_fallback")

                _LOG_HEADERS = ["Server", "X-Powered-By"]
                log_headers = {
                    h: response.headers[h]
                    for h in _LOG_HEADERS
                    if h in response.headers
                }
                log.info(
                    "%s: got status code %i, "
                    "retrying with feedparser User-Agent; "
                    "relevant response headers: %s",
                    request.url,
                    response.status_code,
                    log_headers,
                )

                request.headers["User-Agent"] = f"{fallback_prefix} {current_ua}"

                response = yield request
