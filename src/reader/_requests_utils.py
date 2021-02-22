"""
Requests utilities. Contains no business logic.

"""
from dataclasses import astuple
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TypeVar
from typing import Union

import requests.adapters
from typing_extensions import Protocol


_T = TypeVar('_T')


class _RequestPlugin(Protocol):
    def __call__(
        self,
        session: requests.Session,
        request: requests.Request,
        **kwargs: Any,
    ) -> Optional[requests.Request]:  # pragma: no cover
        ...


class _ResponsePlugin(Protocol):
    def __call__(
        self,
        session: requests.Session,
        response: requests.Response,
        request: requests.Request,
        **kwargs: Any,
    ) -> Optional[requests.Request]:  # pragma: no cover
        ...


@dataclass
class SessionHooks:

    request: Sequence[_RequestPlugin] = field(default_factory=list)
    response: Sequence[_ResponsePlugin] = field(default_factory=list)

    def copy(self: _T) -> _T:
        return type(self)(*(list(v) for v in astuple(self)))


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

    session: requests.Session = field(default_factory=requests.Session)
    hooks: SessionHooks = field(default_factory=SessionHooks)

    def get(
        self,
        url: Union[str, bytes],
        headers: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> requests.Response:
        # kwargs get passed to requests.BaseAdapter.send();
        # can be any of: stream, timeout, verify, cert, proxies

        request = requests.Request('GET', url, headers=headers)

        for request_hook in self.hooks.request:
            request = request_hook(self.session, request, **kwargs) or request

        response = self.session.send(
            self.session.prepare_request(request),  # type: ignore
            **kwargs,
        )

        for response_hook in self.hooks.response:
            new_request = response_hook(self.session, response, request, **kwargs)
            if new_request is None:
                continue

            # TODO: will this fail if stream=False?
            response.close()

            # TODO: is this assert needed? yes, we should raise a custom exception though
            assert isinstance(new_request, requests.Request)

            request = new_request
            response = self.session.send(
                self.session.prepare_request(request),  # type: ignore
                **kwargs,
            )

        return response

    def __enter__(self: _T) -> _T:
        return self

    def __exit__(self, *args: Any) -> None:
        self.session.close()


TimeoutType = Union[None, float, Tuple[float, float], Tuple[float, None]]


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
