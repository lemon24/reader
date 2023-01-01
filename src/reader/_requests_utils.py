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


class RequestPlugin(Protocol):
    def __call__(
        self,
        session: requests.Session,
        request: requests.Request,
        **kwargs: Any,
    ) -> requests.Request | None:  # pragma: no cover
        ...


class ResponsePlugin(Protocol):
    def __call__(
        self,
        session: requests.Session,
        response: requests.Response,
        request: requests.Request,
        **kwargs: Any,
    ) -> requests.Request | None:  # pragma: no cover
        ...


Headers = Mapping[str, str]
TimeoutType = Union[None, float, tuple[float, float], tuple[float, None]]

DEFAULT_TIMEOUT = (3.05, 60)


@dataclass
class SessionFactory:

    """Manage the lifetime of a session.

    TODO: callable

    """

    user_agent: str | None = None
    timeout: TimeoutType = DEFAULT_TIMEOUT

    #: TODO
    request_hooks: Sequence[RequestPlugin] = field(default_factory=list)

    #: TODO
    response_hooks: Sequence[ResponsePlugin] = field(default_factory=list)

    session: SessionWrapper | None = None

    def __call__(self) -> SessionWrapper:
        session = SessionWrapper(
            request_hooks=list(self.request_hooks),
            response_hooks=list(self.response_hooks),
        )

        # lazy import (https://github.com/lemon24/reader/issues/297)
        from ._requests_utils_lazy import TimeoutHTTPAdapter

        timeout_adapter = TimeoutHTTPAdapter(self.timeout)
        session.session.mount('https://', timeout_adapter)
        session.session.mount('http://', timeout_adapter)

        if self.user_agent:
            session.session.headers['User-Agent'] = self.user_agent

        return session

    def transient(self) -> ContextManager[SessionWrapper]:
        if self.session:
            return nullcontext(self.session)
        return self()

    @contextmanager
    def persistent(self) -> Iterator[SessionWrapper]:
        # note: this is NOT threadsafe, but is reentrant

        if self.session:  # pragma: no cover
            yield self.session
            return

        with self() as session:
            self.session = session
            try:
                yield session
            finally:
                self.session = None


_T = TypeVar('_T')


def _make_session() -> requests.Session:
    # lazy import (https://github.com/lemon24/reader/issues/297)
    global requests
    import requests

    return requests.Session()


@dataclass
class SessionWrapper:

    """Minimal wrapper over requests.Sessions.

    Only provides a limited get() method.

    Provides hooks to:

    * modify the Request (not PreparedRequest) before it is sent
    * repeat the Request depending on the Response

    TODO: contextmanager, use factory for hooks

    Details on why the extension methods built into Requests
    (adapters, hooks['response']) were not enough:
    https://github.com/lemon24/reader/issues/155#issuecomment-668716387

    """

    #: TODO
    session: requests.Session = field(default_factory=_make_session)

    request_hooks: Sequence[RequestPlugin] = field(default_factory=list)
    response_hooks: Sequence[ResponsePlugin] = field(default_factory=list)

    def __post_init__(self) -> None:
        # lazy import (https://github.com/lemon24/reader/issues/297)
        global requests
        import requests

    def get(
        self, url: str | bytes, headers: Headers | None = None, **kwargs: Any
    ) -> requests.Response:
        """TODO"""
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
        # TODO: use typing.Self instead of _T
        return self

    def __exit__(self, *args: Any) -> None:
        self.session.close()
