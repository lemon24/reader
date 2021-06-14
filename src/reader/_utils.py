import itertools
import logging
import multiprocessing.dummy
import warnings
from contextlib import contextmanager
from functools import wraps
from queue import Queue
from textwrap import dedent
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
    get_things: Callable[[int, Optional[_T]], Iterable[Tuple[_U, _T]]],
    chunk_size: int,
    last: Optional[_T] = None,
    limit: int = 0,
) -> Iterable[_U]:
    """
    count_to_ten(4, None) -> ('one', 1), ..., ('four', 4)
    count_to_ten(0, None) -> ('one', 1), ..., ('ten', 10)
    count_to_ten(4, 4) -> ('five', 5), ..., ('eight', 8)
    count_to_ten(0, 4) -> ('five', 5), ..., ('ten', 10)

    join_paginated_iter(count_to_ten, 4, None) -> one, ..., ten (3 calls)
    join_paginated_iter(count_to_ten, 0, None) -> one, ..., ten (1 call)
    join_paginated_iter(count_to_ten, 4, 4) -> five, ..., ten (2 calls)
    join_paginated_iter(count_to_ten, 0, 4) -> five, ..., ten (1 call)
    join_paginated_iter(count_to_ten, 4, 4, limit=5) -> five, ..., nine (2 calls)
    join_paginated_iter(count_to_ten, 0, 4, limit=5) -> five, ..., nine (1 call)

    """
    # At the moment get_things must take positional arguments.
    # We could make it work with kwargs by using protocols,
    # but mypy gets confused about partials with kwargs.
    # https://github.com/python/mypy/issues/1484

    if not chunk_size:
        # When chunk_size is 0, don't chunk the query.
        #
        # This will ensure there are no missing/duplicated entries, but
        # will block database writes until the whole generator is consumed.
        #
        # Currently not exposed through the public API.
        #
        things = get_things(limit, last)
        yield from (t for t, _ in things)
        return

    remaining = limit

    while True:
        if limit:
            if not remaining:
                break
            to_get = min(remaining, chunk_size)
            remaining = max(0, remaining - to_get)
        else:
            to_get = chunk_size

        things = list(get_things(to_get, last))
        if not things:
            break

        _, last = things[-1]

        yield from (t for t, _ in things)

        if len(things) < to_get:
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


def deprecated_wrapper(
    old_name: str, func: F, deprecated_in: str, removed_in: str
) -> F:
    @wraps(func)
    def old_func(*args, **kwargs):  # type: ignore
        warnings.warn(
            f"{old_name}() is deprecated "
            f"and will be removed in reader {removed_in}. "
            f"Use {func.__name__}() instead.",
            DeprecationWarning,
        )
        return func(*args, **kwargs)

    old_func.__name__ = old_name
    old_func.__doc__ = dedent(
        f"""Deprecated alias for :meth:`{func.__name__}`.

        .. deprecated:: {deprecated_in}
            This method will be removed in *reader* {removed_in}.
            Use :meth:`{func.__name__}` instead.

        """
    )

    return cast(F, old_func)
