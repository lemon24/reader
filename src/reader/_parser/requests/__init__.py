"""
Requests utilities. Contains no business logic.

"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import ContextManager
from typing import Generator
from typing import Protocol
from typing import TYPE_CHECKING
from typing import TypedDict
from typing import TypeVar
from typing import Union

import httpx

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
CachingInfo = TypedDict('CachingInfo', {'etag': str, 'last-modified': str}, total=False)

DEFAULT_TIMEOUT = (3.05, 60)


class UAFallbackAuth(httpx.Auth):
    """Auth handler that retries 403 responses with a fallback User-Agent.
    
    This is a httpx-native implementation that uses auth_flow to handle retries
    declaratively, without the need for next_request patches or while loops.
    Used by the ua_fallback plugin.
    """
    
    def __init__(self, fallback_ua: str, original_request_url: str | None = None):
        """Initialize UA fallback auth.
        
        Args:
            fallback_ua: The fallback User-Agent string to use on retry.
            original_request_url: For logging purposes (optional).
        """
        self.fallback_ua = fallback_ua
        self.original_request_url = original_request_url
    
    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        """Handle request/response with declarative retry logic.
        
        Yields:
            httpx.Request: The request to send.
        """
        response = yield request
        
        # If we got 403 and haven't tried the fallback UA yet, retry
        if response.status_code == 403:
            current_ua = request.headers.get('User-Agent', '')
            fallback_prefix = self.fallback_ua.partition(' ')[0]
            
            # Only retry if we haven't already used the fallback UA
            if current_ua and not current_ua.startswith(fallback_prefix):
                import logging
                log = logging.getLogger('reader.plugins.ua_fallback')
                
                _LOG_HEADERS = ['Server', 'X-Powered-By']
                log_headers = {
                    h: response.headers[h] for h in _LOG_HEADERS if h in response.headers
                }
                log.info(
                    "%s: got status code %i, "
                    "retrying with feedparser User-Agent; "
                    "relevant response headers: %s",
                    request.url,
                    response.status_code,
                    log_headers,
                )
                
                request.headers['User-Agent'] = f'{fallback_prefix} {current_ua}'
                
                response = yield request


@dataclass
class SessionFactory:
    """Manage the lifetime of a session.

    To get new session, :meth:`call<__call__>` the factory directly.

    """

    user_agent: str | None = None
    timeout: TimeoutType = DEFAULT_TIMEOUT

    request_hooks: list[Callable[[httpx.Request], None]] = field(default_factory=list)
    response_hooks: list[Callable[[httpx.Response], None]] = field(default_factory=list)
    
    # Custom auth handler (can be set by plugins like ua_fallback)
    custom_auth: httpx.Auth | None = None

    client: httpx.Client | None = None

    def __call__(self) -> httpx.Client:
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
        
        return httpx.Client(
            timeout=timeout_obj,
            headers=headers,
            event_hooks={
                'request': list(self.request_hooks),
                # Response hooks kept for backward compatibility (tests)
                # but ua_fallback now uses custom_auth instead
                'response': list(self.response_hooks),
            },
            auth=self.custom_auth,  # Use plugin-provided auth (e.g., UAFallbackAuth)
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
