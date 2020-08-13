import functools
import importlib
import inspect
import posixpath
from urllib.parse import urlparse

import pytest


def make_url_base(feed_url):
    url_base = urlparse(feed_url)
    url_base = url_base._replace(
        path=posixpath.dirname(url_base.path), params='', query='', fragment=''
    ).geturl()
    if url_base:
        url_base = url_base.rstrip('/') + '/'

    rel_base = url_base if feed_url.startswith('http') else ''

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
