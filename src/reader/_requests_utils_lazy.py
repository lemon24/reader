from __future__ import annotations

from typing import Any

import requests

from ._requests_utils import TimeoutType


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
