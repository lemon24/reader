from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from typing import ContextManager
from typing import IO

import requests

from .. import RetrieveResult
from .. import wrap_exceptions
from ...exceptions import ParseError
from .._http_utils import parse_options_header
from ..requests import SessionWrapper


@dataclass
class HTTPRetriever:

    """http(s):// retriever that uses Requests.

    Following the implementation in:
    https://github.com/kurtmckee/feedparser/blob/develop/feedparser/http.py

    "Porting" notes:

    No need to add Accept-encoding (requests seems to do this already).

    No need to add Referer / User-Agent / Authorization / custom request
    headers, as they are not exposed in the Parser.__call__() interface
    (not yet, at least).

    We should add:

    * If-None-Match (http_etag)
    * If-Modified-Since (http_last_modified)
    * Accept (feedparser.(html.)ACCEPT_HEADER)
    * A-IM ("feed")

    NOTE: This is a very old docstring, header setting is spread in multiple places

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
        request_headers = {}
        if http_accept:
            request_headers['Accept'] = http_accept

        with self.get_session() as session:
            with wrap_exceptions(url, "while getting feed"):
                response, http_etag, http_last_modified = _caching_get(
                    session,
                    url,
                    http_etag,
                    http_last_modified,
                    headers=request_headers,
                    stream=True,
                )

            if response.status_code == 304:
                response.close()
                yield None
                return

            response_headers = response.headers.copy()
            response_headers.setdefault('content-location', response.url)

            # The content is already decoded by requests/urllib3.
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


def _caching_get(
    session: SessionWrapper,
    url: str,
    http_etag: str | None = None,
    http_last_modified: str | None = None,
    **kwargs: Any,
) -> tuple[requests.Response, str | None, str | None]:
    headers = dict(kwargs.pop('headers', {}))
    if http_etag:
        headers.setdefault('If-None-Match', http_etag)
        # https://tools.ietf.org/html/rfc3229#section-10.5.3
        headers.setdefault('A-IM', 'feed')
    if http_last_modified:
        headers.setdefault('If-Modified-Since', http_last_modified)

    response = session.get(url, headers=headers, **kwargs)

    try:
        response.raise_for_status()
    except Exception as e:
        raise ParseError(url, message="bad HTTP status code") from e

    http_etag = response.headers.get('ETag', http_etag)
    http_last_modified = response.headers.get('Last-Modified', http_last_modified)

    return response, http_etag, http_last_modified
