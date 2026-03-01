"""
Requests utilities. Contains no business logic.

"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import TypedDict
from typing import Union

from ..._utils import lazy_import


if TYPE_CHECKING:  # pragma: no cover
    import httpx

    from ._lazy import UAFallbackAuth as UAFallbackAuth


__getattr__ = lazy_import(__name__, ['UAFallbackAuth'])


Headers = Mapping[str, str]
TimeoutType = Union[None, float, tuple[float, float], tuple[float, None]]
CachingInfo = TypedDict('CachingInfo', {'etag': str, 'last-modified': str}, total=False)

DEFAULT_TIMEOUT = (3.05, 60)


@dataclass
class SessionFactory:
    """Manage the lifetime of a session.

    To get new session, :meth:`call<__call__>` the factory directly.

    """

    user_agent: str | None = None
    timeout: TimeoutType = DEFAULT_TIMEOUT

    request_hooks: list[Callable[[httpx.Request], None]] = field(default_factory=list)
    response_hooks: list[Callable[[httpx.Response], None]] = field(default_factory=list)

    # Custom auth handler (can be set by plugins like ua_fallback).
    custom_auth: httpx.Auth | Callable[[], httpx.Auth] | None = None

    client: httpx.Client | None = None

    def __call__(self) -> httpx.Client:
        import httpx

        # httpx.Timeout can accept a tuple directly: (connect, read)
        # or all four parameters must be set explicitly
        if isinstance(self.timeout, tuple):
            timeout_obj = httpx.Timeout(
                connect=self.timeout[0],
                read=self.timeout[1],
                write=None,
                pool=None,
            )
        else:
            timeout_obj = httpx.Timeout(self.timeout)  # default timeout

        headers = {}
        if self.user_agent:
            headers['User-Agent'] = self.user_agent
        auth = self.custom_auth() if callable(self.custom_auth) else self.custom_auth

        return httpx.Client(
            timeout=timeout_obj,
            headers=headers,
            event_hooks={
                'request': list(self.request_hooks),
                # Response hooks kept for backward compatibility (tests)
                # but ua_fallback now uses custom_auth instead
                'response': list(self.response_hooks),
            },
            auth=auth,
            follow_redirects=True,
        )

    @contextmanager
    def transient(self) -> Iterator[httpx.Client]:
        """Return the current :meth:`persistent` client, or a new one.

        If a new client was created,
        it is closed once the context manager is exited.

        Returns:
            contextmanager(httpx.Client):

        """
        if self.client:
            yield self.client
        else:
            client = self()
            try:
                yield client
            finally:
                client.close()

    @contextmanager
    def persistent(self) -> Iterator[httpx.Client]:
        """Register a persistent client with this factory.

        While the context manager returned by this method is entered,
        all :meth:`persistent` and :meth:`transient` calls
        will return the same client.
        The client is closed once the outermost :meth:`persistent`
        context manager is exited.

        Plugins should use :meth:`transient`.

        Reentrant, but NOT threadsafe.

        Returns:
            contextmanager(httpx.Client):

        """
        if self.client:
            yield self.client
            return

        self.client = self()
        try:
            yield self.client
        finally:
            self.client.close()
            self.client = None
