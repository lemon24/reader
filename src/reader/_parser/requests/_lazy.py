from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Self
from typing import TYPE_CHECKING
from typing import TypeVar

import requests

from . import CachingInfo
from . import TimeoutType


if TYPE_CHECKING:  # pragma: no cover
    from . import Headers
    from . import RequestHook
    from . import ResponseHook


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


_T = TypeVar('_T')


@dataclass
class SessionWrapper:
    """Minimal wrapper over a :class:`requests.Session`.

    Only provides a limited :meth:`get` method.

    Can be used as a context manager (closes the session on exit).

    """

    # TODO: contextmanager, use factory for hooks

    # Details on why the extension methods built into Requests
    # (adapters, hooks['response']) were not enough:
    # https://github.com/lemon24/reader/issues/155#issuecomment-668716387

    #: The underlying :class:`requests.Session`.
    session: requests.Session = field(default_factory=requests.Session)

    #: Sequence of :class:`RequestHook`\s.
    request_hooks: Sequence[RequestHook] = field(default_factory=list)
    #: Sequence of :class:`ResponseHook`\s.
    response_hooks: Sequence[ResponseHook] = field(default_factory=list)

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

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        self.session.close()


def _str_value(d: Any | None, key: str) -> str | None:
    if not d:
        return None
    assert isinstance(d, dict), d
    rv = d.get(key)
    if rv is None:
        return None
    assert isinstance(rv, str), rv
    return rv
