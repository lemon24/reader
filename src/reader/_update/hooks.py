from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from typing import Any
from typing import Generic
from typing import Self
from typing import TypeVar

from .._logging import get_logger
from ..exceptions import SingleUpdateHookError
from ..exceptions import UpdateHookError
from ..exceptions import UpdateHookErrorGroup

logger = get_logger('reader.update.hooks')


FuncType = Callable[..., Any]
F = TypeVar('F', bound=FuncType)


class Hooks(Generic[F]):
    def __init__(self, name: str):
        self.name = name
        self.hooks: list[F] = []

    def run(
        self,
        resource_id: tuple[str, ...] | None,
        *args: Any,
        return_exceptions: bool = False,
    ) -> list[SingleUpdateHookError]:
        log = logger.bind(when=self.name, **log_resource_id(resource_id))

        rv = []
        for hook in self.hooks:
            start = time.monotonic()
            try:
                self._run(hook, args)
            except Exception as e:
                wrapper = SingleUpdateHookError(self.name, hook, resource_id)
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

    def _run(self, hook: F, args: tuple[Any]) -> None:
        posargs = 0
        varargs = False
        for p in inspect.signature(hook).parameters.values():
            if p.kind == p.POSITIONAL_ONLY or p.kind == p.POSITIONAL_OR_KEYWORD:
                posargs += 1
            if p.kind == p.VAR_POSITIONAL:
                varargs = True
        if not varargs:
            args = args[:posargs]
        hook(*args)


class HookErrorGrouper:
    def __init__(self, message: str):
        self.message = message
        self.exceptions: list[UpdateHookError] = []
        self.seen_dedupe_keys: set[Any] = set()

    def run(
        self,
        hooks: Hooks[F],
        resource_id: tuple[str, ...] | None,
        *args: Any,
        limit: int = 0,
    ) -> None:
        for exc in hooks.run(resource_id, *args, return_exceptions=True):
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

    def __enter__(self) -> Self:
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
