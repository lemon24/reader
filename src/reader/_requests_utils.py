"""
Requests utilities. Contains no business logic.

"""
from __future__ import annotations

from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import ContextManager
from typing import Protocol
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import Union

if TYPE_CHECKING:  # pragma: no cover
    import requests


_T = TypeVar('_T')


class _RequestPlugin(Protocol):
    def __call__(
        self,
        session: requests.Session,
        request: requests.Request,
        **kwargs: Any,
    ) -> requests.Request | None:  # pragma: no cover
        ...


class _ResponsePlugin(Protocol):
    def __call__(
        self,
        session: requests.Session,
        response: requests.Response,
        request: requests.Request,
        **kwargs: Any,
    ) -> requests.Request | None:  # pragma: no cover
        ...


def _make_session() -> requests.Session:
    # lazy import (https://github.com/lemon24/reader/issues/297)
    import requests

    return requests.Session()


@dataclass
class SessionWrapper:

    """Minimal wrapper over requests.Sessions.

    Only provides a limited get() method.

    Provides hooks to:

    * modify the Request (not PreparedRequest) before it is sent
    * repeat the Request depending on the Response

    Details on why the extension methods built into Requests
    (adapters, hooks['response']) were not enough:
    https://github.com/lemon24/reader/issues/155#issuecomment-668716387

    """

    session: requests.Session = field(default_factory=_make_session)
    request_hooks: Sequence[_RequestPlugin] = field(default_factory=list)
    response_hooks: Sequence[_ResponsePlugin] = field(default_factory=list)

    def __post_init__(self) -> None:
        # lazy import (https://github.com/lemon24/reader/issues/297)
        global requests
        import requests

    def get(
        self,
        url: str | bytes,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
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

    def __enter__(self: _T) -> _T:
        return self

    def __exit__(self, *args: Any) -> None:
        self.session.close()


TimeoutType = Union[None, float, tuple[float, float], tuple[float, None]]

DEFAULT_TIMEOUT = (3.05, 60)


def TimeoutHTTPAdapter(timeout: TimeoutType) -> requests.adapters.HTTPAdapter:
    # lazy import (https://github.com/lemon24/reader/issues/297)

    global TimeoutHTTPAdapter

    if isinstance(TimeoutHTTPAdapter, type):  # pragma: no cover
        return TimeoutHTTPAdapter(timeout)

    import requests

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

    return TimeoutHTTPAdapter(timeout)


@dataclass
class SessionFactory:

    """Manage the lifetime of a session."""

    user_agent: str | None = None
    timeout: TimeoutType = DEFAULT_TIMEOUT
    request_hooks: Sequence[_RequestPlugin] = field(default_factory=list)
    response_hooks: Sequence[_ResponsePlugin] = field(default_factory=list)
    session: SessionWrapper | None = None

    def make_session(self) -> SessionWrapper:
        session = SessionWrapper(
            request_hooks=list(self.request_hooks),
            response_hooks=list(self.response_hooks),
        )

        timeout_adapter = TimeoutHTTPAdapter(self.timeout)
        session.session.mount('https://', timeout_adapter)
        session.session.mount('http://', timeout_adapter)

        if self.user_agent:
            session.session.headers['User-Agent'] = self.user_agent

        return session

    def transient(self) -> ContextManager[SessionWrapper]:
        if self.session:
            return nullcontext(self.session)
        return self.make_session()

    @contextmanager
    def persistent(self) -> Iterator[SessionWrapper]:
        # note: this is NOT threadsafe, but is reentrant

        if self.session:  # pragma: no cover
            yield self.session
            return

        with self.make_session() as session:
            self.session = session
            try:
                yield session
            finally:
                self.session = None
