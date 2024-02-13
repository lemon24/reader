from __future__ import annotations

import sqlite3
from collections.abc import Callable
from collections.abc import Iterable
from typing import Any
from typing import TypeVar

from ..exceptions import StorageError
from ._sql_utils import paginated_query
from ._sql_utils import Query
from ._sqlite_utils import DBError
from ._sqlite_utils import LocalConnectionFactory
from ._sqlite_utils import setup_db
from ._sqlite_utils import wrap_exceptions
from ._sqlite_utils import wrap_exceptions_iter


MISSING_MIGRATION_DETAIL = (
    "; you may have skipped some required migrations, see "
    "https://reader.readthedocs.io/en/latest/changelog.html#removed-migrations-3-0"
)


_T = TypeVar('_T')


class StorageBase:
    #: Private storage API.
    chunk_size = 2**8

    @wrap_exceptions(StorageError)
    def __init__(
        self,
        path: str,
        timeout: float | None = None,
        wal_enabled: bool | None = True,
        factory: type[sqlite3.Connection] | None = None,
    ):
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs['timeout'] = timeout
        if factory:  # pragma: no cover
            kwargs['factory'] = factory

        with wrap_exceptions(StorageError, "error while opening database"):
            self.factory = LocalConnectionFactory(path, **kwargs)
            db = self.factory()

        with wrap_exceptions(StorageError, "error while setting up database"):
            try:
                try:
                    self.setup_db(db, wal_enabled)
                except BaseException:
                    db.close()
                    raise
            except DBError as e:
                message = str(e)
                if 'no migration' in message:
                    message += MISSING_MIGRATION_DETAIL
                raise StorageError(message=message) from None

        self.path = path
        self.timeout = timeout

    def get_db(self) -> sqlite3.Connection:
        """Private storage API (used by search)."""
        try:
            return self.factory()
        except DBError as e:
            raise StorageError(message=str(e)) from None

    @staticmethod
    def setup_db(db: sqlite3.Connection, wal_enabled: bool | None) -> None:
        """Private storage API (used by tests)."""
        from . import _schema
        from . import APPLICATION_ID, MINIMUM_SQLITE_VERSION, REQUIRED_SQLITE_FUNCTIONS

        return setup_db(
            db,
            create=_schema.create_all,
            version=_schema.VERSION,
            migrations=_schema.MIGRATIONS,
            id=APPLICATION_ID,
            minimum_sqlite_version=MINIMUM_SQLITE_VERSION,
            required_sqlite_functions=REQUIRED_SQLITE_FUNCTIONS,
            wal_enabled=wal_enabled,
        )

    @wrap_exceptions(StorageError)
    def __enter__(self) -> None:
        try:
            self.factory.__enter__()
        except DBError as e:
            raise StorageError(message=str(e)) from None

    @wrap_exceptions(StorageError)
    def __exit__(self, *_: Any) -> None:
        self.factory.__exit__()

    @wrap_exceptions(StorageError)
    def close(self) -> None:
        self.factory.close()

    @wrap_exceptions_iter(StorageError)
    def paginated_query(
        self,
        make_query: Callable[[], tuple[Query, dict[str, Any]]],
        limit: int | None = None,
        last: tuple[Any, ...] | None = None,
        row_factory: Callable[[tuple[Any, ...]], _T] | None = None,
    ) -> Iterable[_T]:
        return paginated_query(
            self.get_db(),
            make_query,
            self.chunk_size,
            limit or 0,
            last,
            row_factory,
        )
