import itertools
import logging
import multiprocessing.dummy
from contextlib import contextmanager
from queue import Queue
from typing import Any
from typing import Callable
from typing import cast
from typing import Iterable
from typing import Iterator
from typing import no_type_check
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TypeVar
from typing import Union

from .types import MISSING
from .types import MissingType


FuncType = Callable[..., Any]
F = TypeVar('F', bound=FuncType)

_T = TypeVar('_T')
_U = TypeVar('_U')


def zero_or_one(
    it: Iterable[_U],
    make_exc: Callable[[], Exception],
    default: Union[MissingType, _T] = MISSING,
) -> Union[_U, _T]:
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


def join_paginated_iter(
    get_things: Callable[[int, Optional[_T]], Iterable[Tuple[_U, _T]]], chunk_size: int,
) -> Iterable[_U]:
    # At the moment get_things must take positional arguments.
    # We could make it work with kwargs by using protocols,
    # but mypy gets confused about partials with kwargs.
    # https://github.com/python/mypy/issues/1484

    last = None
    while True:

        things = get_things(chunk_size, last)

        # When chunk_size is 0, don't chunk the query.
        #
        # This will ensure there are no missing/duplicated entries, but
        # will block database writes until the whole generator is consumed.
        #
        # Currently not exposed through the public API.
        #
        if not chunk_size:
            yield from (t for t, _ in things)
            break

        things = list(things)
        if not things:
            break

        _, last = things[-1]

        yield from (t for t, _ in things)

        if len(things) < chunk_size:
            break


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


@contextmanager
def make_pool_map(workers: int) -> Iterator[F]:
    pool = multiprocessing.dummy.Pool(workers)
    try:
        yield wrap_map(pool.imap_unordered, workers)
    finally:
        pool.close()
        pool.join()


def wrap_map(map: F, workers: int) -> F:
    """Ensure map() calls next() on its iterable in the current thread.

    multiprocessing.dummy.Pool.imap_unordered seems to pass
    the iterable to the worker threads, which call next() on it.

    For generators, this means the generator code runs in the worker thread,
    which is a problem if the generator calls stuff that shouldn't be called
    across threads; e.g., calling a sqlite3.Connection method results in:

        sqlite3.ProgrammingError: SQLite objects created in a thread
        can only be used in that same thread. The object was created
        in thread id 1234 and this is thread id 5678.

    """

    @no_type_check
    def wrapper(func, iterable):
        sentinel = object()
        queue = Queue()

        for _ in range(workers):
            queue.put(next(iterable, sentinel))

        for rv in map(func, iter(queue.get, sentinel)):
            queue.put(next(iterable, sentinel))
            yield rv

    return cast(F, wrapper)


@contextmanager
def make_noop_context_manager(thing: _T) -> Iterator[_T]:
    yield thing


class PrefixLogger(logging.LoggerAdapter):

    # if needed, add: with log.push('another prefix'): ...

    def __init__(self, logger: logging.Logger, prefixes: Sequence[str] = ()):
        super().__init__(logger, {})
        self.prefixes = tuple(prefixes)

    @staticmethod
    def _escape(s: str) -> str:  # pragma: no cover
        return '%%'.join(s.split('%'))

    def process(self, msg: str, kwargs: Any) -> Tuple[str, Any]:  # pragma: no cover
        return ': '.join(tuple(self._escape(p) for p in self.prefixes) + (msg,)), kwargs
