from __future__ import annotations

import io
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from typing import cast
from typing import ContextManager
from typing import IO

import httpx

from . import HTTPInfo
from . import NotModified
from . import RetrievedFeed
from . import RetrieveError
from . import wrap_exceptions
from ._http_utils import parse_options_header


@dataclass(frozen=True)
class HTTPRetriever:
    """http(s):// retriever that uses HTTPX.

    Roughly following feedparser's implementation[*]_,
    but currently keeps the same high-level return shape as before.

    .. [*] https://github.com/kurtmckee/feedparser/blob/6.0.10/feedparser/http.py

    """

    get_session: Callable[[], ContextManager[httpx.Client]]

    @contextmanager
    def __call__(
        self,
        url: str,
        caching_info: Any = None,
        accept: str | None = None,
    ) -> Iterator[RetrievedFeed[IO[bytes]]]:
        request_headers = {
            # https://tools.ietf.org/html/rfc3229#section-10.5.3
            # "Accept-Instance-Manipulation"
            # https://www.ctrl.blog/entry/feed-delta-updates.html
            # https://www.ctrl.blog/entry/feed-caching.html
            "A-IM": "feed",
        }
        if accept:
            request_headers["Accept"] = accept

        if isinstance(caching_info, dict):
            etag = caching_info.get("etag")
            last_modified = caching_info.get("last-modified")
            if isinstance(etag, str) and etag:
                request_headers.setdefault("If-None-Match", etag)
            if isinstance(last_modified, str) and last_modified:
                request_headers.setdefault("If-Modified-Since", last_modified)

        error = RetrieveError(url)

        with wrap_exceptions(error):
            error._message = "while getting feed"
            with self.get_session() as client:
                response = client.get(url, headers=request_headers)

                headers_dict = dict(response.headers)
                headers_dict.pop("content-encoding", None)
                if "content-location" not in headers_dict:
                    headers_dict["content-location"] = str(response.url)
                headers = httpx.Headers(headers_dict)

                http_info = HTTPInfo(response.status_code, headers)
                error.http_info = http_info

                if response.status_code == 304:
                    raise NotModified(url, http_info=http_info)

                error._message = "bad HTTP status code"
                response.raise_for_status()

                content_type = headers.get("content-type")
                if content_type:
                    mime_type, _ = parse_options_header(content_type)
                else:
                    mime_type = None

                resource = io.BytesIO(response.content)

                response_caching_info: dict[str, str] = {}
                if response.is_success:
                    if etag := headers.get("etag"):
                        response_caching_info["etag"] = etag
                    if last_modified := headers.get("last-modified"):
                        response_caching_info["last-modified"] = last_modified

                error._message = "while reading feed"
                yield RetrievedFeed(
                    cast(IO[bytes], resource),
                    mime_type,
                    cast(dict[str, Any] | None, response_caching_info or None),
                    http_info,
                    slow_to_read=False,
                )

    def validate_url(self, url: str) -> None:
        try:
            parsed = httpx.URL(url)
        except httpx.InvalidURL as e:
            raise ValueError(str(e)) from None

        if parsed.scheme not in ("http", "https"):
            raise ValueError("url must use http or https")
        if not parsed.host:
            raise ValueError("url must include a host")
