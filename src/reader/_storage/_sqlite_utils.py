"""
sqlite3 utilities. Contains no business logic.

"""

from __future__ import annotations

import functools
import sqlite3
import sys
import threading
import time
import traceback
import weakref
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from contextlib import closing
from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import no_type_check
from typing import TypeVar


SQLiteType = TypeVar('SQLiteType', None, int, float, str, bytes)


@contextmanager
def ddl_transaction(db: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Automatically commit/rollback transactions containing DDL statements.

    Usage:

        with ddl_transaction(db):
            db.execute(...)
            db.execute(...)

    Note: ddl_transaction() does not work with executescript().

    Normally, one would expect to be able to use DDL statements in a
    transaction like so:

        with db:
            db.execute(ddl_statement)
            db.execute(other_statement)

    Initially, this worked around https://bugs.python.org/issue10740;
    the sqlite3 transaction handling would trigger an implicit commit
    if the first execute() was a DDL statement, which prevented it from
    being rolled back if there was an exception after it.

    This was fixed in Python 3.6, but there are still some cases that behave
    in the same way, e.g.:

        db = sqlite3.connect(':memory:')
        try:
            with db:
                db.execute("create table t (a, b);")
                1 / 0
        except ZeroDivisionError:
            pass
        # table t exists even if it shouldn't

    https://docs.python.org/3.5/library/sqlite3.html#controlling-transactions

    """
    # initialy from https://github.com/lemon24/boomtime/blob/master/boomtime/db.py
    isolation_level = db.isolation_level
    try:
        db.isolation_level = None
        db.execute("BEGIN;")
        yield db
        db.execute("COMMIT;")
    except Exception:
        db.execute("ROLLBACK;")
        raise
    finally:
        db.isolation_level = isolation_level


@contextmanager
def wrap_exceptions(
    exc_type: Callable[[str], Exception],
    op_exc_types: Mapping[str, Callable[[str], Exception]] = {},  # noqa: B006
    message: str = "unexpected error",
) -> Iterator[None]:
    """Wrap sqlite3 exceptions in a custom exception.

    Only wraps exceptions that are unlikely to be programming errors (bugs),
    can only be fixed by the user (e.g. access permission denied), and aren't
    domain-related (those should have other custom exceptions).

    We intentionally rely on the error message, because:

    * the DB-API exceptions are somewhat fuzzy in their meaning
    * we can't access the SQLite result code prior to Python 3.11
    * even having the primary result code (added in 3.11):
      * it's generic SQLITE_ERROR for a lot of errors we care about
        ("no such ...", "... already exists", invalid FTS5 queries)
      * we need the table name so we don't accidentally shadow bugs
      * we need the extended result code for the same reason
        (e.g. SQLITE_CONSTRAINT vs SQLITE_CONSTRAINT_FOREIGNKEY)
      * ProgrammingError usually does not have an error code

    Full discussion at https://github.com/lemon24/reader/issues/21

    """
    try:
        yield

    except sqlite3.OperationalError as e:
        e_msg = str(e).lower()
        for fragment, op_exc_type in op_exc_types.items():
            if fragment.lower() in e_msg:
                raise op_exc_type(str(e)) from None
        raise exc_type(message) from e

    except sqlite3.ProgrammingError as e:
        if "cannot operate on a closed database" in str(e).lower():
            raise exc_type("operation on closed database") from None

        raise

    except sqlite3.DatabaseError as e:
        # most sqlite3 exceptions are subclasses of DatabaseError
        if type(e) is sqlite3.DatabaseError:  # pragma: no cover
            # test_database_error_other should test both branches of this, but doesn't for some reason

            # SQLITE_CORRUPT: either on connect(), or after
            if "file is not a database" in str(e).lower():
                raise exc_type(message) from e

        raise

    except DBError as e:
        raise exc_type(str(e)) from None


@contextmanager
def foreign_keys_off(db: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Disable foreign key checks temporarily.

    This is useful when changing the schema in ways not supported by ALTER[1]
    (e.g. changing column constraints, renaming/removing columns).

    You should check for any foreign key constraint violations
    (see foreign_key_check() below), preferably inside of a transaction.

    Note: foreign_keys_off() must be used outside transactions, because[2]:

    > It is not possible to enable or disable foreign key constraints
    > in the middle of a multi-statement transaction [...]. Attempting
    > to do so does not return an error; it simply has no effect.

    [1]: https://sqlite.org/lang_altertable.html#otheralter
    [2]: https://sqlite.org/foreignkeys.html#fk_enable

    """
    assert not db.in_transaction, "foreign_keys_off must be used outside transactions"
    (foreign_keys,) = db.execute("PRAGMA foreign_keys;").fetchone()
    try:
        db.execute("PRAGMA foreign_keys = OFF;")
        yield db
    finally:
        db.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'};")


def foreign_key_check(db: sqlite3.Connection) -> None:
    """Check foreign key constraint violations.

    Raises:
        IntegrityError: If there were any violations.

    """
    failed_checks = list(db.execute("PRAGMA foreign_key_check;"))
    if not failed_checks:
        return
    # TODO: More details regarding what failed.
    raise IntegrityError("FOREIGN KEY constraint failed")


class DBError(Exception):
    display_name = "database error"

    def __str__(self) -> str:
        return f"{self.display_name}: {super().__str__()}"


class SchemaVersionError(DBError):
    display_name = "schema version error"


class IntegrityError(DBError):
    display_name = "integrity error"


class RequirementError(DBError):
    display_name = "database requirement error"


class IdError(DBError):
    display_name = "application id error"


db_errors = [DBError, SchemaVersionError, IntegrityError, RequirementError]


_DBFunction = Callable[[sqlite3.Connection], None]


@dataclass
class HeavyMigration:
    create: _DBFunction
    version: int  # must be positive
    migrations: dict[int, _DBFunction]
    missing_suffix: str = ''

    def migrate(self, db: sqlite3.Connection) -> None:
        with foreign_keys_off(db), ddl_transaction(db):
            version = self.get_version(db)

            if not version:
                if table_count(db) != 0:
                    raise DBError("database with no version already has tables")

                self.create(db)
                self.set_version(db, self.version)
                return

            if version == self.version:
                return

            if version > self.version:
                raise SchemaVersionError(f"invalid version: {version}")

            # version < self.version

            for from_version in range(version, self.version):
                to_version = from_version + 1
                migration = self.migrations.get(from_version)
                if migration is None:
                    raise SchemaVersionError(
                        f"no migration from {from_version} to {to_version}; "
                        f"expected migrations for all versions "
                        f"later than {version}" + self.missing_suffix
                    )

                migration(db)
                self.set_version(db, to_version)

                try:
                    foreign_key_check(db)
                except IntegrityError as e:
                    raise IntegrityError(
                        f"after migrating to version {to_version}: {e}"
                    ) from None

        # cannot VACUUM from within a transaction,
        # so just do it any time migrations happen
        db.execute("VACUUM;")

    @staticmethod
    def get_version(db: sqlite3.Connection) -> int:
        return get_int_pragma(db, 'user_version')

    @staticmethod
    def set_version(db: sqlite3.Connection, version: int) -> None:
        set_int_pragma(db, 'user_version', version)


def ensure_application_id(db: sqlite3.Connection, id: bytes) -> bool:
    if len(id) != 4:
        raise ValueError(f"id must be exactly 4 bytes long, got: {id!r}")

    new_id = int.from_bytes(id, 'big')

    old_id = get_int_pragma(db, 'application_id')
    if old_id:
        if old_id != new_id:
            raise IdError(f"invalid existing application id: 0x{old_id:x}")
        return False

    if table_count(db) != 0:
        raise DBError("database with no application id already has tables")

    set_int_pragma(db, 'application_id', new_id)
    return True


def get_int_pragma(db: sqlite3.Connection, pragma: str) -> int:
    with closing(db.cursor()) as cursor:
        (value,) = cursor.execute(f"PRAGMA {pragma};").fetchone()
    assert isinstance(value, int), value  # for mypy
    return value


def set_int_pragma(
    db: sqlite3.Connection, pragma: str, value: int, lower_bound: int = 0
) -> None:
    if not isinstance(value, int):
        raise ValueError(f"{pragma} must be an integer, got {value!r}")
    if lower_bound is not None and value < lower_bound:
        raise ValueError(f"{pragma} must be >={lower_bound}, got {value!r}")

    with closing(db.cursor()) as cursor:
        cursor.execute(f"PRAGMA {pragma} = {value};")


def table_count(db: sqlite3.Connection) -> int:
    with closing(db.cursor()) as cursor:
        (value,) = cursor.execute("select count(*) from sqlite_master;").fetchone()
    assert isinstance(value, int), value  # for mypy
    return value


def require_version(db: sqlite3.Connection, version_info: tuple[int, ...]) -> None:
    with closing(db.cursor()) as cursor:
        ((version,),) = cursor.execute("SELECT sqlite_version();")

    version_ints = tuple(int(i) for i in version.split('.'))

    if version_info > version_ints:
        raise RequirementError(
            "at least SQLite version {} required, {} installed".format(
                ".".join(str(i) for i in version_info),
                ".".join(str(i) for i in sqlite3.sqlite_version_info),
            )
        )


FUNCTION_TESTS = {
    # storage
    'json_array_length': "select json_array_length('[]')",
    # search
    'json': "select json(1)",
    'json_object': "select json_object('key', 1)",
    'json_group_array': "select json_group_array(1)",
    'json_each': "select * from json_each(1)",
}


def require_functions(db: sqlite3.Connection, names: Sequence[str]) -> None:
    missing = set()
    with closing(db.cursor()) as cursor:
        for name in names:
            sql = FUNCTION_TESTS.get(name)
            if not sql:
                raise ValueError(f"no test for function: {name}")

            try:
                list(cursor.execute(sql))
            except sqlite3.OperationalError as e:
                if "no such" not in str(e):
                    # likely a bug in the sql, raise
                    raise
                missing.add(name)

    if missing:
        raise RequirementError(f"required SQLite functions missing: {sorted(missing)}")


def setup_db(
    db: sqlite3.Connection,
    *,
    id: bytes,
    minimum_sqlite_version: tuple[int, ...] = (),
    required_sqlite_functions: Sequence[str] = (),
    migration: HeavyMigration | None = None,
) -> None:
    if minimum_sqlite_version:
        require_version(db, minimum_sqlite_version)
    if required_sqlite_functions:
        require_functions(db, required_sqlite_functions)

    new_db = ensure_application_id(db, id)

    with closing(db.cursor()) as cursor:
        cursor.execute("PRAGMA foreign_keys = ON;")

        # We enable WAL exactly once, when the database if first created.
        #
        # Every cursor up to here must be closed explictly, othewise we get
        # "cannot commit transaction - SQL statements in progress" on PyPy;
        # this is still happening as of February 2024:
        #
        # https://github.com/pypy/pypy/issues/3080 (closed)
        # https://github.com/pypy/pypy/issues/3183
        #
        if new_db:
            cursor.execute("PRAGMA journal_mode = WAL;")

    if migration:
        migration.migrate(db)


def rowcount_exactly_one(
    cursor: sqlite3.Cursor, make_exc: Callable[[], Exception]
) -> None:
    if cursor.rowcount == 0:
        raise make_exc()
    assert cursor.rowcount == 1, "shouldn't have more than 1 row"


class UsageError(DBError):
    display_name = "usage error"


class LocalConnectionFactory:
    """Maintain a set of connections to the same database, one per thread.

    connect() on object creation in the creating thread,
    and on the first call in all other threads.

    When close() is called in a thread, run "pragma optimize" and
    close the connection in that thread.

    If close() is not called, attempt to call close() before the thread ends.
    This is unreliable: it doesn't work on PyPy,
    or if the thread was not created through the threading module.

    To account for that and for long-running threads,
    run optimize regularly (currently, every 1024 calls).

    When used as a context manager, don't run optimize regulary,
    and call close() automatically when exiting the with block.

    https://github.com/lemon24/reader/issues/206#issuecomment-1183660880

    """

    INLINE_OPTIMIZE_TIMEOUT = 0.1

    def __init__(
        self, path: str, setup_db: _DBFunction = lambda _: None, **kwargs: Any
    ):
        self.path = path
        self.setup_db = setup_db
        self.kwargs = kwargs
        if kwargs.get('uri'):  # pragma: no cover
            raise NotImplementedError("is_private() does not work for uri=True")
        self.attached: dict[str, str] = {}
        self._local = _LocalConnectionFactoryState()
        self._local.is_creating_thread = True
        self._other_threads = False
        # connect immediately, so exceptions are raised before the first call
        self.__call__()

    def __call__(self) -> sqlite3.Connection:
        db = self._local.db
        if db:
            if not self._local.context_stack:
                if self._should_optimize(self._local.call_count):
                    self._optimize(db, self.INLINE_OPTIMIZE_TIMEOUT)
                self._local.call_count += 1
            return db

        if self.is_private() and not self._local.is_creating_thread:
            raise UsageError(
                "cannot use a private database "
                "from threads other than the creating thread"
            )

        if self.is_private() and self._local.closed:
            raise UsageError("cannot reuse a private database after close()")

        if not self._local.is_creating_thread:
            self._other_threads = True

        self._local.db = db = sqlite3.connect(self.path, **self.kwargs)
        assert db is not None, "for mypy"
        self._local.call_count = 0

        try:
            self.setup_db(db)
        except BaseException:
            db.close()
            raise

        # http://threebean.org/blog/atexit-for-threads/
        # works on cpython (finalizer runs in thread),
        # but not on pypy (finalizer runs in main thread);
        # also see https://bugs.python.org/issue14073
        self._local.finalizer = weakref.finalize(
            threading.current_thread(), self._close, db
        )

        for name, path in self.attached.items():
            self._attach(db, name, path)

        return db

    def __enter__(self) -> sqlite3.Connection:
        self._local.context_stack.append(None)
        return self.__call__()

    def __exit__(self, *args: Any) -> None:
        self._local.context_stack.pop()
        if not self._local.context_stack and not self.is_private():
            self.close()

    def close(self) -> None:
        if self._local.finalizer:
            self._local.finalizer()
            self._local.db = None
            self._local.finalizer = None
            self._local.call_count = 0
            self._local.closed = True

    @classmethod
    def _close(cls, db: sqlite3.Connection) -> None:
        try:
            try:
                cls._optimize(db)
            finally:
                db.close()
        except sqlite3.ProgrammingError as e:
            message = str(e).lower()
            # calling close() a second time is a noop
            if "cannot operate on a closed database" in message:  # pragma: no cover
                return
            # can't close() a connection from a thread that didn't create it;
            # SQLAlchemy ignores this as well in SingletonThreadPool.dispose()
            if "objects created in a thread" in message:
                return
            raise

    @staticmethod
    def _optimize(db: sqlite3.Connection, timeout: float = 0) -> None:
        # Don't wait too much for a lock, it means the database is busy,
        # and now is likely not a good time to run optimize.
        # Also prevents rare "database is locked" errors in certain conditions
        # (e.g. test_asyncio_shared on Linux, on Python 3.8 but not later).
        # https://www2.fossil-scm.org/fossil/artifact/b47bdc17?ln=2556-2559

        # TODO: Once SQLite 3.32 becomes widespread, use "PRAGMA analysis_limit"
        # to prevent "PRAGMA optimize" from taking too long.
        # https://github.com/lemon24/reader/issues/143#issuecomment-663433197

        # busy_timeout causes PyPy 7.3.9 to segfault during tests
        on_pypy = sys.implementation.name == 'pypy'
        ctx = busy_timeout(db, timeout) if not on_pypy else nullcontext(db)

        try:
            with ctx:
                db.execute("PRAGMA optimize;")
        except sqlite3.OperationalError as e:  # pragma: no cover
            message = str(e).lower()
            if "database is locked" not in message:
                raise

    @staticmethod
    def _should_optimize(count: int) -> bool:
        if count > 1024:
            return count % 2048 == 0
        return count in {2, 4, 8, 16, 64, 256, 1024}

    def attach(self, name: str, path: str) -> None:
        if not self._local.is_creating_thread:
            raise UsageError(
                "cannot call attach() from threads other than the creating thread"
            )
        if self._other_threads:
            raise UsageError(
                "cannot call attach() after the factory was used from other threads"
            )
        if self._is_private(name):  # pragma: no cover
            raise NotImplementedError(f"cannot attach private database: {name!r}")
        if name in self.attached:  # pragma: no cover
            raise ValueError(f"database already attached: {name!r}")

        self.attached[name] = path
        db = self._local.db
        assert db is not None
        self._attach(db, name, path)

    def _attach(self, db: sqlite3.Connection, name: str, path: str) -> None:
        db.execute("ATTACH DATABASE ? AS ?;", (path, name))

    def is_private(self) -> bool:
        return self._is_private(self.path)

    @staticmethod
    def _is_private(path: str) -> bool:
        """Does connect(path) from another thread connect to a different database?

        With uri=False (the default), only ':memory:' and '' are private.

        With uri=True:

        * file::memory: and file: are private
        * file::memory:?&cache=shared is shared (one per process)
        * file:mydb?mode=memory&cache=shared is shared
        * file:?&cache=shared is ???

        https://www.sqlite.org/c3ref/open.html#urifilenamesinsqlite3open
        https://www.sqlite.org/uri.html

        """
        return path in [':memory:', '']


class _LocalConnectionFactoryState(threading.local):
    def __init__(self) -> None:
        self.db: sqlite3.Connection | None = None
        self.finalizer: (
            weakref.finalize[[sqlite3.Connection], threading.Thread] | None
        ) = None
        self.is_creating_thread: bool = False
        self.context_stack: list[None] = []
        self.call_count: int = 0
        self.closed: bool = False


@contextmanager
def busy_timeout(
    db: sqlite3.Connection, seconds: float
) -> Iterator[sqlite3.Connection]:
    new = int(seconds * 1000)
    (old,) = db.execute("PRAGMA busy_timeout;").fetchone()
    db.execute(f"PRAGMA busy_timeout = {new};")
    try:
        yield db
    finally:
        db.execute(f"PRAGMA busy_timeout = {old};")


def adapt_datetime(val: datetime) -> str:
    assert val.tzinfo == timezone.utc, val
    val = val.replace(tzinfo=None)
    return val.isoformat(" ")


def convert_timestamp(val: str) -> datetime:
    rv = datetime.fromisoformat(val)
    assert not rv.tzinfo, val
    rv = rv.replace(tzinfo=timezone.utc)
    return rv


# BEGIN DebugConnection

# No type annotations or coverage for this;
# its only used for debugging and not exposed publicly.


@no_type_check
def _make_debug_method_wrapper(method, stmt=False):  # pragma: no cover
    @functools.wraps(method)
    def wrapper(self, *args):
        data = {
            'method': method if isinstance(method, str) else method.__name__,
            'start': time.time(),
        }
        if stmt:
            data['stmt'] = args[0] if args else None

        try:
            tb = traceback.extract_stack()
            frame = tb[-2]
            data['caller'] = frame.filename, frame.name
        except IndexError:
            pass

        try:
            io_counters = self.connection._io_counters
        except AttributeError:
            io_counters = self._io_counters

        if io_counters:
            import psutil  # type: ignore

            fields = ['read_count', 'write_count', 'read_bytes', 'write_bytes']
            process = psutil.Process()
            # this will fail on MacOS, but that's OK
            start_io_counters = process.io_counters()

        start = time.perf_counter()
        try:
            if callable(method):
                return method(self, *args)
        except Exception as e:
            data['exception'] = f"{type(e).__module__}.{type(e).__qualname__}: {e}"
            raise
        finally:
            end = time.perf_counter()
            data['duration'] = end - start

            if io_counters:
                end_io_counters = process.io_counters()
                data['io_counters'] = {
                    f: getattr(end_io_counters, f) - getattr(start_io_counters, f)
                    for f in fields
                }

            self._log(data)

    return wrapper


@no_type_check
def _make_debug_connection_cls():  # pragma: no cover
    # we create the classes in a function to work around
    # typing.no_type_check not supporting classes (yet);
    # https://github.com/python/mypy/issues/607

    @no_type_check
    class DebugCursor(sqlite3.Cursor):
        def _log(self, data):
            # can't rely on id(self) as it's likely to be reused
            data['cursor'] = self._id
            self.connection._log(data)

        execute = _make_debug_method_wrapper(sqlite3.Cursor.execute, stmt=True)
        executemany = _make_debug_method_wrapper(sqlite3.Cursor.executemany, stmt=True)
        close = _make_debug_method_wrapper(sqlite3.Cursor.close)
        __del__ = _make_debug_method_wrapper('__del__')

    @no_type_check
    class DebugConnection(sqlite3.Connection):
        """sqlite3 connection subclass for debugging stuff.

        >>> debug = logging.getLogger('whatever').debug
        >>> class MyDebugConnection(DebugConnection):
        ...     _log_method = staticmethod(lambda data: debug(json.dumps(data)))
        ...     _set_trace = True
        ...
        >>> db = sqlite3.connect('', factory=MyDebugConnection)

        """

        _set_trace = False
        _io_counters = False

        @staticmethod
        def _log_method(data):
            raise NotImplementedError

        _cursor_factory = DebugCursor

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._next_cursor_id = 0
            if self._set_trace:
                trace_wrapper = _make_debug_method_wrapper('~trace', stmt=True)

                def trace(stmt):
                    return trace_wrapper(self, stmt)

                self.set_trace_callback(trace)

        def _log(self, data):
            # less likely for this to be the same address
            data['connection'] = id(self)
            self._log_method(data)

        def cursor(self, factory=None):
            if factory:
                raise NotImplementedError("cursor(factory=...) not supported")
            cursor = super().cursor(factory=self._cursor_factory)
            cursor._id = self._next_cursor_id
            self._next_cursor_id += 1
            return cursor

        close = _make_debug_method_wrapper(sqlite3.Connection.close)
        __enter__ = _make_debug_method_wrapper(sqlite3.Connection.__enter__)
        __exit__ = _make_debug_method_wrapper(sqlite3.Connection.__exit__)
        # the sqlite3 objects don't have a __del__
        __del__ = _make_debug_method_wrapper('__del__')

    return DebugConnection


DebugConnection = _make_debug_connection_cls()


# END DebugConnection
