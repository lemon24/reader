from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from .._logging import get_logger
from ..exceptions import SingleUpdateHookError
from ..exceptions import UpdateHookError
from ..exceptions import UpdateHookErrorGroup

logger = get_logger('reader.update.hooks')


class UpdateHooks:
    def __init__(self, target: Any):
        self.target = target
        self.hooks: dict[str, list[Callable[..., None]]] = defaultdict(list)

    def run(
        self,
        when: str,
        resource_id: tuple[str, ...] | None,
        *args: Any,
        return_exceptions: bool = False,
    ) -> list[SingleUpdateHookError]:
        log = logger.bind(when=when, **log_resource_id(resource_id))

        rv = []
        for hook in self.hooks[when]:
            start = time.monotonic()
            try:
                hook(self.target, *args)
            except Exception as e:
                wrapper = SingleUpdateHookError(when, hook, resource_id)
                wrapper.__cause__ = e
                if not return_exceptions:
                    raise wrapper
                rv.append(wrapper)
            finally:
                end = time.monotonic()
                try:
                    name = hook.__module__ + ':' + hook.__qualname__
                except AttributeError:
                    name = repr(hook)

                timing = round(end - start, 3)
                log_method = log.debug if timing < 1 else log.warning
                log_method('hook_timing', hook=name, time=timing)

        return rv

    def group(self, message: str) -> _UpdateHookErrorGrouper:
        return _UpdateHookErrorGrouper(self, message)


class _UpdateHookErrorGrouper:
    def __init__(self, hooks: UpdateHooks, message: str):
        self.hooks = hooks
        self.message = message
        self.exceptions: list[UpdateHookError] = []
        self.seen_dedupe_keys: set[Any] = set()

    def run(
        self,
        when: str,
        resource_id: tuple[str, ...] | None,
        *args: Any,
        limit: int = 0,
    ) -> None:
        for exc in self.hooks.run(when, resource_id, *args, return_exceptions=True):
            self.add(exc, resource_id, limit)

    def add(self, exc: UpdateHookError, dedupe_key: Any = None, limit: int = 0) -> None:
        # TODO: test error deduping; also, the logic may not be correct?
        if limit and dedupe_key not in self.seen_dedupe_keys:  # pragma: no cover
            if len(self.seen_dedupe_keys) >= limit:
                logger.error("too many hook errors, discarding exception", exc_info=exc)
                return
            self.seen_dedupe_keys.add(dedupe_key)
        self.exceptions.append(exc)

    def close(self) -> None:
        if self.exceptions:
            raise UpdateHookErrorGroup(self.message, self.exceptions)

    def __enter__(self) -> _UpdateHookErrorGrouper:
        return self

    def __exit__(self, _: Any, exc: BaseException, __: Any) -> None:
        # bare SingleUpdateHookError was intended to raise, don't catch it
        if isinstance(exc, UpdateHookErrorGroup):
            self.add(exc)
        self.close()


def log_resource_id(resource_id: tuple[str, ...] | None) -> dict[str, str]:
    rv: dict[str, str] = {}
    if not resource_id:
        return rv
    rv['feed'] = resource_id[0]
    if len(resource_id) >= 2:
        rv['entry'] = resource_id[1]
    return rv
