from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import ContextManager
from typing import IO

import requests

from ..exceptions import ParseError
from . import RetrieveResult
from . import wrap_exceptions
from ._http_utils import parse_options_header
from .requests import SessionWrapper


@dataclass(frozen=True)
class HTTPRetriever:
    """http(s):// retriever that uses Requests.

    Roughly following feedparser's implementation[*]_,
    but header setting has been split to multiple places:

    * Accept-Encoding is set by Requests by default
    * User-Agent is set on the session by SessionFactory
    * If-None-Match is set by SessionWrapper.caching_get()
    * If-Modified-Since is set by SessionWrapper.caching_get()

    .. [*] https://github.com/kurtmckee/feedparser/blob/6.0.10/feedparser/http.py

    """

    get_session: Callable[[], ContextManager[SessionWrapper]]
    slow_to_read = True

    @contextmanager
    def __call__(
        self,
        url: str,
        http_etag: str | None = None,
        http_last_modified: str | None = None,
        http_accept: str | None = None,
    ) -> Iterator[RetrieveResult[IO[bytes]] | None]:
        request_headers = {
            # https://tools.ietf.org/html/rfc3229#section-10.5.3
            # "Accept-Instance-Manipulation"
            # https://www.ctrl.blog/entry/feed-delta-updates.html
            # https://www.ctrl.blog/entry/feed-caching.html
            'A-IM': 'feed',
        }
        if http_accept:
            request_headers['Accept'] = http_accept

        with self.get_session() as session:
            with wrap_exceptions(url, "while getting feed"):
                response, http_etag, http_last_modified = session.caching_get(
                    url,
                    http_etag,
                    http_last_modified,
                    headers=request_headers,
                    stream=True,
                )

            try:
                response.raise_for_status()
            except Exception as e:
                raise ParseError(url, message="bad HTTP status code") from e

            if response.status_code == 304:
                response.close()
                yield None
                return

            response_headers = response.headers.copy()
            response_headers.setdefault('content-location', response.url)

            # https://datatracker.ietf.org/doc/html/rfc9110#name-content-encoding
            # Content-Encoding is the counterpart of Accept-Encoding;
            # it is about binary transformations (mainly compression),
            # not text encoding (Content-Type charset does that).
            # We let Requests/urllib3 take care of it and remove the header,
            # so parsers (like feedparser) don't do it a second time.
            response_headers.pop('content-encoding', None)
            response.raw.decode_content = True

            content_type = response_headers.get('content-type')
            mime_type: str | None
            if content_type:
                mime_type, _ = parse_options_header(content_type)
            else:
                mime_type = None

            with wrap_exceptions(url, "while reading feed"), response:
                yield RetrieveResult(
                    response.raw,
                    mime_type,
                    http_etag,
                    http_last_modified,
                    response_headers,
                )

    def validate_url(self, url: str) -> None:
        with self.get_session() as session_wrapper:
            session = session_wrapper.session
            session.get_adapter(url)
            session.prepare_request(requests.Request('GET', url))
