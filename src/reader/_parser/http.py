from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from typing import cast
from typing import ContextManager
from typing import IO

import requests

from . import HTTPInfo
from . import NotModified
from . import RetrievedFeed
from . import RetrieveError
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
            'A-IM': 'feed',
        }
        if accept:
            request_headers['Accept'] = accept

        error = RetrieveError(url)

        with self.get_session() as session, wrap_exceptions(error):
            error._message = "while getting feed"
            response, response_caching_info = session.caching_get(
                url, caching_info, request_headers, stream=True
            )

            with response:
                http_info = HTTPInfo(response.status_code, response.headers)
                error.http_info = http_info

                if response.status_code == 304:
                    raise NotModified(url, http_info=http_info)

                error._message = "bad HTTP status code"
                response.raise_for_status()

                response.headers.setdefault('content-location', response.url)

                # https://datatracker.ietf.org/doc/html/rfc9110#name-content-encoding
                # Content-Encoding is the counterpart of Accept-Encoding;
                # it is about binary transformations (mainly compression),
                # not text encoding (Content-Type charset does that).
                # We let Requests/urllib3 take care of it and remove the header,
                # so parsers (like feedparser) don't do it a second time.
                response.headers.pop('content-encoding', None)
                response.raw.decode_content = True

                content_type = response.headers.get('content-type')
                if content_type:
                    mime_type, _ = parse_options_header(content_type)
                else:
                    mime_type = None

                error._message = "while reading feed"
                yield RetrievedFeed(
                    cast(IO[bytes], response.raw),
                    mime_type,
                    # https://github.com/python/mypy/issues/4976
                    cast(dict[str, Any] | None, response_caching_info),
                    http_info,
                    slow_to_read=True,
                )

    def validate_url(self, url: str) -> None:
        with self.get_session() as session_wrapper:
            session = session_wrapper.session
            session.get_adapter(url)
            session.prepare_request(requests.Request('GET', url))
