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


Headers = Mapping[str, str]
TimeoutType = Union[None, float, tuple[float, float], tuple[float, None]]

DEFAULT_TIMEOUT = (3.05, 60)


@dataclass
class SessionFactory:

    """Manage the lifetime of a session.

    To get new session, :meth:`call<__call__>` the factory directly.

    """

    user_agent: str | None = None
    timeout: TimeoutType = DEFAULT_TIMEOUT

    #: Sequence of :class:`RequestHook`\s to be associated with new sessions.
    request_hooks: Sequence[RequestHook] = field(default_factory=list)

    #: Sequence of :class:`ResponseHook`\s to be associated with new sessions.
    response_hooks: Sequence[ResponseHook] = field(default_factory=list)

    session: SessionWrapper | None = None

    def __call__(self) -> SessionWrapper:
        """Create a new session.

        Returns:
            SessionWrapper:

        """
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
        """Return the current :meth:`persistent` session, or a new one.

        If a new session was created,
        it is closed once the context manager is exited.

        Returns:
            contextmanager(SessionWrapper):

        """
        if self.session:
            return nullcontext(self.session)
        return self()

    @contextmanager
    def persistent(self) -> Iterator[SessionWrapper]:
        """Register a persistent session with this factory.

        While the context manager returned by this method is entered,
        all :meth:`persistent` and :meth:`transient` calls
        will return the same session.
        The session is closed once the outermost :meth:`persistent`
        context manager is exited.

        Plugins should use :meth:`transient`.

        Reentrant, but NOT threadsafe.

        Returns:
            contextmanager(SessionWrapper):

        """
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

    """Minimal wrapper over a :class:`requests.Session`.

    Only provides a limited :meth:`get` method.

    Can be used as a context manager (closes the session on exit).

    """

    # TODO: contextmanager, use factory for hooks

    # Details on why the extension methods built into Requests
    # (adapters, hooks['response']) were not enough:
    # https://github.com/lemon24/reader/issues/155#issuecomment-668716387

    #: The underlying :class:`requests.Session`.
    session: requests.Session = field(default_factory=_make_session)

    #: Sequence of :class:`RequestHook`\s.
    request_hooks: Sequence[RequestHook] = field(default_factory=list)
    #: Sequence of :class:`ResponseHook`\s.
    response_hooks: Sequence[ResponseHook] = field(default_factory=list)

    def __post_init__(self) -> None:
        # lazy import (https://github.com/lemon24/reader/issues/297)
        global requests
        import requests

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

    def __enter__(self: _T) -> _T:
        # TODO: use typing.Self instead of _T
        return self

    def __exit__(self, *args: Any) -> None:
        self.session.close()
