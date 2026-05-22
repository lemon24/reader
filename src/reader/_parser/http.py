from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import cast
from typing import IO
from typing import Protocol
from typing import Self
from typing import TypedDict
from typing import Union

import requests

from . import DEFAULT_TIMEOUT
from . import Headers
from . import HTTPInfo
from . import NotModified
from . import RetrievedFeed
from . import RetrieveError
from . import wrap_exceptions
from ._http_utils import parse_options_header

TimeoutType = Union[None, float, tuple[float, float], tuple[float, None]]
CachingInfo = TypedDict('CachingInfo', {'etag': str, 'last-modified': str}, total=False)


class RequestHook(Protocol):
    """Hook to modify a :class:`~requests.Request` before it is sent."""

    def __call__(
        self,
        session: requests.Session,
        request: requests.Request,
        **kwargs: Any,
    ) -> requests.Request | None:  # pragma: no cover
        """Modify a request before it is sent.

        Args:
            session (requests.Session): The session that will send the request.
            request (requests.Request): The request to be sent.

        Keyword Args:
            **kwargs: Will be passed to :meth:`~requests.adapters.BaseAdapter.send`.

        Returns:
            requests.Request or None:
            A (possibly modified) request to be sent.
            If none, send the initial request.

        """


class ResponseHook(Protocol):
    """Hook to repeat a request depending on the :class:`~requests.Response`."""

    def __call__(
        self,
        session: requests.Session,
        response: requests.Response,
        request: requests.Request,
        **kwargs: Any,
    ) -> requests.Request | None:  # pragma: no cover
        """Repeat a request  depending on the response.

        Args:
            session (requests.Session): The session that sent the request.
            request (requests.Request): The sent request.
            response (requests.Response): The received response.

        Keyword Args:
            **kwargs: Were passed to :meth:`~requests.adapters.BaseAdapter.send`.

        Returns:
            requests.Request or None:
            A (possibly new) request to be sent,
            or None, to return the current response.

        """


@dataclass
class HTTPRetriever:
    """http(s):// retriever that uses Requests.

    Roughly following feedparser's implementation[*]_,
    but header setting has been split to multiple places:

    * Accept-Encoding is set by Requests by default
    # FIXME
    * User-Agent is set on the session by SessionFactory
    * If-None-Match is set by SessionWrapper.caching_get()
    * If-Modified-Since is set by SessionWrapper.caching_get()

    .. [*] https://github.com/kurtmckee/feedparser/blob/6.0.10/feedparser/http.py

    """

    user_agent: str | None = None
    timeout: TimeoutType = DEFAULT_TIMEOUT

    # Details on why the extension methods built into Requests
    # (adapters, hooks['response']) were not enough:
    # https://github.com/lemon24/reader/issues/155#issuecomment-668716387

    #: Sequence of :class:`RequestHook`\s.
    request_hooks: list[RequestHook] = field(default_factory=list)
    #: Sequence of :class:`ResponseHook`\s.
    response_hooks: list[ResponseHook] = field(default_factory=list)

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

        with wrap_exceptions(error):
            error._message = "while getting feed"
            response, response_caching_info = self.caching_get(
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
        with self:
            self.session.get_adapter(url)
            self.session.prepare_request(requests.Request('GET', url))

    def get(
        self, url: str | bytes, headers: Headers | None = None, **kwargs: Any
    ) -> requests.Response:
        """Like Requests :meth:`~requests.Session.get`,
        but apply :attr:`request_hooks` and :attr:`response_hooks`.

        Args:
            url (str): Passed to :class:`~requests.Request`.
            headers (dict(str, str)): Passed to :class:`~requests.Request`.

        Keyword Args:
            **kwargs: Passed to :meth:`~requests.adapters.BaseAdapter.send`.

        Returns:
            requests.Response:

        """
        # kwargs get passed to requests.BaseAdapter.send();
        # can be any of: stream, timeout, verify, cert, proxies

        request = requests.Request('GET', url, headers=headers)

        for request_hook in self.request_hooks:
            request = request_hook(self.session, request, **kwargs) or request

        response = self.session.send(self.session.prepare_request(request), **kwargs)

        for response_hook in self.response_hooks:
            new_request = response_hook(self.session, response, request, **kwargs)
            if new_request is None:
                continue

            # TODO: will this fail if stream=False?
            response.close()

            # TODO: is this assert needed? yes, we should raise a custom exception though
            assert isinstance(new_request, requests.Request)

            request = new_request
            response = self.session.send(
                self.session.prepare_request(request), **kwargs
            )

        return response

    def caching_get(
        self,
        url: str,
        caching_info: Any = None,
        headers: Headers | None = None,
        **kwargs: Any,
    ) -> tuple[requests.Response, CachingInfo | None]:
        """Like :meth:`get()`, but set and return caching headers.

        caching_get(url, old_caching_info) -> response, new_caching_info

        """
        headers = dict(headers or ())

        etag = _str_value(caching_info, 'etag')
        last_modified = _str_value(caching_info, 'last-modified')
        if etag:
            headers.setdefault('If-None-Match', etag)
        if last_modified:
            headers.setdefault('If-Modified-Since', last_modified)

        response = self.get(url, headers=headers, **kwargs)

        response_caching_info: CachingInfo = {}
        if response.ok:
            etag = response.headers.get('ETag')
            if etag:
                response_caching_info['etag'] = etag
            last_modified = response.headers.get('Last-Modified', last_modified)
            if last_modified:
                response_caching_info['last-modified'] = last_modified

        return response, response_caching_info or None

    @property
    def session(self) -> requests.Session:
        assert self._session
        return self._session

    def __post_init__(self) -> None:
        self._session: requests.Session | None = None
        self._lock = threading.RLock()
        self._depth = 0

    def __enter__(self) -> Self:
        with self._lock:
            if self._depth == 0:
                self._session = session = requests.Session()
                timeout_adapter = TimeoutHTTPAdapter(self.timeout)
                session.mount('https://', timeout_adapter)
                session.mount('http://', timeout_adapter)
                if self.user_agent:
                    session.headers['User-Agent'] = self.user_agent
            self._depth += 1
        return self

    def __exit__(self, *args: Any) -> None:
        with self._lock:
            self._depth -= 1
            if self._depth == 0:
                self._session.close()  # type: ignore[union-attr]
                self._session = None


def _str_value(d: Any | None, key: str) -> str | None:
    if not d:
        return None
    assert isinstance(d, dict), d
    rv = d.get(key)
    if rv is None:
        return None
    assert isinstance(rv, str), rv
    return rv


class TimeoutHTTPAdapter(requests.adapters.HTTPAdapter):
    """Add a default timeout to requests.

    https://requests.readthedocs.io/en/master/user/advanced/#timeouts
    https://github.com/psf/requests/issues/3070#issuecomment-205070203

    TODO: Remove when psf/requests#3070 gets fixed.

    """

    def __init__(self, timeout: TimeoutType, *args: Any, **kwargs: Any):
        self.__timeout = timeout
        super().__init__(*args, **kwargs)

    def send(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault('timeout', self.__timeout)
        return super().send(*args, **kwargs)
