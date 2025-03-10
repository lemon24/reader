from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Callable
from collections.abc import Iterable
from functools import partial
from typing import Any
from typing import TypeVar

from ..exceptions import StorageError
from . import _sqlite_utils
from ._sql_utils import paginated_query
from ._sql_utils import Query


APPLICATION_ID = b'read'

_T = TypeVar('_T')


# also used by tests
CONNECTION_CLS = sqlite3.Connection

debug = os.environ.get('READER_DEBUG_STORAGE', '')
assert set(debug) <= {'m', 't', 'T', 'i'}, f"invalid READER_DEBUG_STORAGE={debug}"

if debug:  # pragma: no cover

    class CONNECTION_CLS(_sqlite_utils.DebugConnection):  # type: ignore # noqa: F811
        _set_trace = 't' or 'T' in debug
        _io_counters = 'i' in debug
        _pid = os.getpid()

        def _log_method(self, data):  # type: ignore
            data['pid'] = self._pid
            stmt = None
            if 'T' in debug:
                stmt = data.pop('stmt', None)
            print('STORAGE_DEBUG', json.dumps(data), file=sys.stderr)
            if stmt:
                print(stmt, file=sys.stderr)


wrap_exceptions = partial(_sqlite_utils.wrap_exceptions, StorageError)


class StorageBase:
    # Private API, used by tests.
    chunk_size = 2**8

    @wrap_exceptions(message="while opening database")
    def __init__(self, path: str, timeout: float | None = None):
        kwargs: dict[str, Any] = {'factory': CONNECTION_CLS}
        if timeout is not None:
            kwargs['timeout'] = timeout

        # at least the "PRAGMA foreign_keys = ON" part of setup_db
        # has to run for every connection (in every thread),
        # since it's not persisted across connections
        self.factory = _sqlite_utils.LocalConnectionFactory(
            path, self.setup_db, **kwargs
        )

    def get_db(self) -> sqlite3.Connection:
        return self.factory()

    @staticmethod
    def setup_db(db: sqlite3.Connection) -> None:
        # Private API, used by tests.

        from . import MINIMUM_SQLITE_VERSION
        from . import REQUIRED_SQLITE_FUNCTIONS
        from ._schema import MIGRATION

        return _sqlite_utils.setup_db(
            db,
            migration=MIGRATION,
            id=APPLICATION_ID,
            minimum_sqlite_version=MINIMUM_SQLITE_VERSION,
            required_sqlite_functions=REQUIRED_SQLITE_FUNCTIONS,
        )

    @wrap_exceptions()
    def __enter__(self) -> None:
        self.factory.__enter__()

    @wrap_exceptions()
    def __exit__(self, *_: Any) -> None:
        self.factory.__exit__()

    @wrap_exceptions()
    def close(self) -> None:
        self.factory.close()

    def paginated_query(
        self,
        make_query: Callable[[], tuple[Query, dict[str, Any]]],
        limit: int | None = None,
        last: tuple[Any, ...] | None = None,
        row_factory: Callable[[tuple[Any, ...]], _T] | None = None,
    ) -> Iterable[_T]:
        with wrap_exceptions():
            yield from paginated_query(
                self.get_db(),
                make_query,
                self.chunk_size,
                limit or 0,
                last,
                row_factory,
            )
