import logging
from functools import partial
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.stdlib import _FixedFindCallerLogger


class LoggerRegistry:

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs
        self.loggers: dict[str, Any] | None = {}

    def get_logger(self, name: str) -> Any:
        if self.loggers is None:  # pragma: no cover
            return structlog.get_logger(name)
        if logger := self.loggers.get(name):  # pragma: no cover
            return logger

        wrapped = logging.getLogger(name)
        wrapped.findCaller = partial(_FixedFindCallerLogger.findCaller, wrapped)  # type: ignore
        logger = structlog.wrap_logger(wrapped, **self.kwargs)
        self.loggers[name] = logger

        return logger

    def enable_structlog(self) -> None:
        if self.loggers is None:  # pragma: no cover
            return

        for name, logger in self.loggers.items():
            logger.__dict__.clear()
            logger.__dict__.update(structlog.get_logger(name).__dict__)

        self.loggers = None


def enrich_exception(_, __, event_dict):  # type: ignore
    if exc_info := event_dict.get('exc_info', None):
        exc_info = structlog.processors._figure_out_exc_info(exc_info)
    if exc_info:
        type, value, _ = exc_info
        event_dict['exception'] = f"{type.__name__}: {value}"
    return event_dict


class Renderer(structlog.processors.LogfmtRenderer):

    def __init__(self, *args, **kwargs):  # type: ignore
        super().__init__(*args, **kwargs)

    def __call__(self, _, __, event_dict):  # type: ignore
        exc_info = event_dict.pop('exc_info', None)
        event = event_dict.pop('event')
        message = super().__call__(_, __, event_dict)
        message = f"{event}  {message}"
        if not exc_info:
            return message
        return (message,), {'exc_info': exc_info}


key_order = ['event', 'status', 'feed', 'entry']
renderer = Renderer(key_order=key_order, drop_missing=True)  # type: ignore
processors = [merge_contextvars, enrich_exception, renderer]
registry = LoggerRegistry(processors=processors, cache_logger_on_first_use=True)

get_logger = registry.get_logger
enable_structlog = registry.enable_structlog
