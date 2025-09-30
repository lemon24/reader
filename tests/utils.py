import functools
import importlib
import inspect
import ntpath
import os.path
import posixpath
import threading
import time
from datetime import datetime
from datetime import timezone
from urllib.parse import urlparse

import pytest


def make_url_base(feed_url):
    # FIXME: this is very brittle (broken query string and fragment support),
    # and also very far away from test_parse where it's used.

    feed_url = str(feed_url)

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


@pytest.fixture
def reload_module(monkeypatch, request):
    modules = []

    def reload_module(module):
        modules.append((module, module.__dict__.copy()))
        return importlib.reload(module)

    def undo():
        monkeypatch.undo()
        # we don't reload the module again,
        # because it creates *new* versions of the old classes,
        # which breaks some modules (e.g. pathlib)
        while modules:
            module, module_dict = modules.pop()
            module.__dict__.clear()
            module.__dict__.update(module_dict)

    request.addfinalizer(undo)
    with monkeypatch.context() as monkeypatch:
        yield reload_module


@pytest.fixture
def monkeypatch_os(monkeypatch):

    def monkeypatch_os(os_name):
        monkeypatch.setattr('os.name', os_name)
        monkeypatch.setattr('os.path', {'nt': ntpath, 'posix': posixpath}[os_name])

    with monkeypatch.context() as monkeypatch:
        yield monkeypatch_os


@pytest.fixture
def monkeypatch_tz(monkeypatch, request):

    def monkeypatch_tz(tz):
        monkeypatch.setenv('TZ', tz)
        time.tzset()

    if hasattr(time, 'tzset'):
        request.addfinalizer(time.tzset)
    with monkeypatch.context() as monkeypatch:
        yield monkeypatch_tz


def utc_datetime(*args, **kwargs):
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


def parametrize_dict(names, values, **kwargs):
    return pytest.mark.parametrize(names, values.values(), ids=values, **kwargs)


class Blocking:
    """Wrap a function in a blocking version of it.

    When entered in the current thread, wait until called from another thread;
    block the call in the other thread until exited in the current thread.

    >>> blocking_print = Blocking(print)
    >>> Thread(target=blocking_print, args=("other",)).start()
    >>> with blocking_print:
    ...     print("main")
    ...
    main
    other

    """

    def __init__(self, fn=None):
        self.fn = fn or (lambda: None)
        self.in_call = threading.Event()
        self.can_return = threading.Event()

    def __call__(self, *args, **kwargs):
        self.in_call.set()
        self.can_return.wait()
        return self.fn(*args, **kwargs)

    def __enter__(self):
        self.in_call.wait()

    def __exit__(self, *_):
        self.can_return.set()
