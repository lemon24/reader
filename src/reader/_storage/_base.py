from __future__ import annotations

import sqlite3
from collections.abc import Callable
from collections.abc import Iterable
from functools import partial
from typing import Any
from typing import TypeVar

from . import _sqlite_utils
from ..exceptions import StorageError
from ._sql_utils import paginated_query
from ._sql_utils import Query


APPLICATION_ID = b'read'

_T = TypeVar('_T')


wrap_exceptions = partial(_sqlite_utils.wrap_exceptions, StorageError)


class StorageBase:
    #: Private storage API.
    chunk_size = 2**8

    @wrap_exceptions(message="while opening database")
    def __init__(
        self,
        path: str,
        timeout: float | None = None,
        factory: type[sqlite3.Connection] | None = None,
    ):
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs['timeout'] = timeout
        if factory:  # pragma: no cover
            kwargs['factory'] = factory

        self.factory = _sqlite_utils.LocalConnectionFactory(path, **kwargs)
        db = self.factory()
        try:
            self.setup_db(db)
        except BaseException:
            db.close()
            raise

        self.path = path
        self.timeout = timeout

    def get_db(self) -> sqlite3.Connection:
        return self.factory()

    @staticmethod
    def setup_db(db: sqlite3.Connection) -> None:
        """Private storage API (used by tests)."""
        from ._schema import MIGRATION
        from . import MINIMUM_SQLITE_VERSION, REQUIRED_SQLITE_FUNCTIONS

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
