import functools
import importlib
import inspect
import os.path
from urllib.parse import urlparse

import pytest


def make_url_base(feed_url):
    # FIXME: this is very brittle (broken query string and fragment support),
    # and also very far away from test_parse where it's used.

    if any(feed_url.startswith(p) for p in ['http:', 'https:', 'file:']):
        sep = '/'
        # ... but not really, we also support file:path\to\thing, I think
    else:
        sep = os.sep

    url_base = sep.join(feed_url.split(sep)[:-1])
    if url_base:
        url_base = url_base.rstrip(sep) + sep

    rel_base = (
        url_base if any(feed_url.startswith(p) for p in ['http:', 'https:']) else ''
    )

    return url_base, rel_base


def rename_argument(original, alias):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            kwargs[original] = kwargs.pop(alias)
            return fn(**kwargs)

        signature = inspect.signature(fn)
        parameters = signature.parameters.copy()
        parameters[alias] = parameters.pop(original).replace(name=alias)
        signature = signature.replace(parameters=parameters.values())

        wrapper.__signature__ = signature

        return wrapper

    return decorator


class Reloader:
    def __init__(self, monkeypatch):
        self.modules = []
        self.monkeypatch = monkeypatch

    def __call__(self, module):
        self.modules.append(module)
        return importlib.reload(module)

    def undo(self):
        # undo monkeypatches before reloading again,
        # to ensure modules are reloaded from a "clean" environment
        self.monkeypatch.undo()
        while self.modules:
            importlib.reload(self.modules.pop())


@pytest.fixture
def reload_module(monkeypatch):
    reloader = Reloader(monkeypatch)
    try:
        yield reloader
    finally:
        reloader.undo()
