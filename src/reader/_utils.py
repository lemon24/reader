from __future__ import annotations

import inspect
import itertools
import sys
import warnings
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import AbstractContextManager as CM
from contextlib import contextmanager
from contextlib import nullcontext
from functools import wraps
from typing import Any
from typing import cast
from typing import TypeVar

FuncType = Callable[..., Any]
F = TypeVar('F', bound=FuncType)

_T = TypeVar('_T')
_U = TypeVar('_U')


class MissingType:
    def __repr__(self) -> str:
        return "no value"


#: Sentinel object used to detect if the `default` argument was provided."""
MISSING = MissingType()


def zero_or_one(
    it: Iterable[_U],
    make_exc: Callable[[], Exception],
    default: MissingType | _T = MISSING,
) -> _U | _T:
    things = list(it)
    if len(things) == 0:
        if isinstance(default, MissingType):
            raise make_exc()
        return default
    elif len(things) == 1:
        return things[0]
    else:
        assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover


def exactly_one(it: Iterable[_U]) -> _U:
    things = list(it)
    if len(things) == 1:
        return things[0]
    else:
        assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover


def chunks(n: int, iterable: Iterable[_T]) -> Iterable[Iterable[_T]]:
    """grouper(2, 'ABCDE') --> AB CD E"""
    # based on https://stackoverflow.com/a/8991553
    it = iter(iterable)
    while True:
        chunk = itertools.islice(it, n)
        try:
            first = next(chunk)
        except StopIteration:
            break
        yield itertools.chain([first], chunk)


def eager_iterable(it: Iterable[_T]) -> Iterable[_T]:
    it = iter(it)
    try:
        return itertools.chain([next(it)], it)
    except StopIteration:
        return it


@contextmanager
def exiting(cm: CM[Any], rv: _T) -> Iterator[_T]:
    try:
        yield rv
    finally:
        cm.__exit__(*sys.exc_info())


# if we substitute MapFunction below, mypy complains
# https://github.com/python/mypy/issues/17551
MapFunction = Callable[[Callable[[_T], _U], Iterable[_T]], Iterator[_U]]


def make_pool_map(
    workers: int,
) -> CM[Callable[[Callable[[_T], _U], Iterable[_T]], Iterator[_U]]]:
    if workers < 1:
        raise ValueError("workers must be a positive integer")
    if workers == 1:
        return nullcontext(map)
    return _make_pool_map(workers)


@contextmanager
def _make_pool_map(
    workers: int,
) -> Iterator[Callable[[Callable[[_T], _U], Iterable[_T]], Iterator[_U]]]:
    # We are using concurrent.futures instead of multiprocessing.dummy
    # because the latter doesn't work on some environments (e.g. AWS Lambda).
    # We are not using executor.map() because it consumes the entire iterable.

    # lazy import (https://github.com/lemon24/reader/issues/297)
    import concurrent.futures

    executor = concurrent.futures.ThreadPoolExecutor(workers)

    def imap_unordered(fn: Callable[[_T], _U], iterable: Iterable[_T]) -> Iterator[_U]:
        iterable = iter(iterable)
        iterable_ended = False
        pending: set[concurrent.futures.Future[_U]] = set()

        while pending or not iterable_ended:
            while len(pending) < workers and not iterable_ended:
                try:
                    arg = next(iterable)
                except StopIteration:
                    iterable_ended = True
                else:
                    pending.add(executor.submit(fn, arg))

            if not pending:  # pragma: no cover
                return

            done, pending = concurrent.futures.wait(
                pending, return_when=concurrent.futures.FIRST_COMPLETED
            )
            while done:
                yield done.pop().result()

    with executor:
        yield imap_unordered


_DEPRECATED_FUNC_WARNING = """\
{old_name}() is deprecated and will be removed in reader {removed_in}. \
Use {new_name}() instead.\
"""
_DEPRECATED_FUNC_DOCSTRING = """\
Deprecated alias for :meth:`{new_name}`.
{doc}
.. deprecated:: {deprecated_in}
    This method will be removed in *reader* {removed_in}.
    Use :meth:`{new_name}` instead.

"""

_DEPRECATED_PROP_WARNING = """\
{old_name} is deprecated and will be removed in reader {removed_in}. \
Use {new_name} instead.\
"""
_DEPRECATED_PROP_DOCSTRING = """\
Deprecated variant of :attr:`{new_name}`.
{doc}
.. deprecated:: {deprecated_in}
    This property will be removed in *reader* {removed_in}.
    Use :attr:`{new_name}` instead.

"""


def _deprecated_wrapper(
    old_name: str,
    new_name: str,
    func: F,
    deprecated_in: str,
    removed_in: str,
    doc: str = '',
    warning_template: str = _DEPRECATED_FUNC_WARNING,
    docstring_template: str = _DEPRECATED_FUNC_DOCSTRING,
) -> F:
    format_kwargs = dict(locals())

    @wraps(func)
    def old_func(*args, **kwargs):  # type: ignore
        warnings.warn(
            warning_template.format_map(format_kwargs),
            DeprecationWarning,
            stacklevel=2,
        )
        return func(*args, **kwargs)

    old_func.__name__ = old_name
    old_func.__doc__ = docstring_template.format_map(format_kwargs)
    return cast(F, old_func)


def deprecated_wrapper(
    old_name: str, func: F, deprecated_in: str, removed_in: str
) -> F:
    return _deprecated_wrapper(old_name, func.__name__, func, deprecated_in, removed_in)


def deprecated(
    new_name: str, deprecated_in: str, removed_in: str, property: bool = False
) -> Callable[[F], F]:
    if not property:
        kwargs = {}
    else:
        kwargs = dict(
            warning_template=_DEPRECATED_PROP_WARNING,
            docstring_template=_DEPRECATED_PROP_DOCSTRING,
        )

    def decorator(func: F) -> F:
        doc = inspect.getdoc(func) or ''
        if doc:  # pragma: no cover
            doc = '\n' + doc + '\n'
        return _deprecated_wrapper(
            func.__name__, new_name, func, deprecated_in, removed_in, doc=doc, **kwargs
        )

    return decorator


def resolve_path(o: object, path: str) -> Any | None:
    try:
        return eval('o' + path, {'o': o})
    except AttributeError:
        return None
