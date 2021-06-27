"""
sqlite3 utilities. Contains no business logic.

"""
import functools
import sqlite3
import time
import traceback
from contextlib import closing
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import Callable
from typing import cast
from typing import Dict
from typing import Iterator
from typing import no_type_check
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TypeVar

from typing_extensions import Protocol


SQLiteType = TypeVar('SQLiteType', None, int, float, str, bytes, datetime)


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
    exc_type: Callable[[str], Exception], message: str = "unexpected error"
) -> Iterator[None]:
    """Wrap sqlite3 exceptions in a custom exception.

    Only wraps exceptions that are unlikely to be programming errors (bugs),
    can only be fixed by the user (e.g. access permission denied), and aren't
    domain-related (those should have other custom exceptions).

    This is an imprecise science, since the DB-API exceptions are somewhat
    fuzzy in their meaning and we can't access the SQLite result code.

    Full discussion at https://github.com/lemon24/reader/issues/21

    """
    try:
        yield

    except sqlite3.OperationalError as e:
        raise exc_type(message) from e

    except sqlite3.ProgrammingError as e:
        if "cannot operate on a closed database" in str(e).lower():
            raise exc_type("operation on closed database")

        raise

    except sqlite3.DatabaseError as e:

        # most sqlite3 exceptions are subclasses of DatabaseError
        if type(e) is sqlite3.DatabaseError:  # pragma: no cover
            # test_database_error_other should test both branches of this, but doesn't for some reason

            # SQLITE_CORRUPT: either on connect(), or after
            if "file is not a database" in str(e).lower():
                raise exc_type(message) from e

        raise


FuncType = Callable[..., Any]
F = TypeVar('F', bound=FuncType)


def wrap_exceptions_iter(exc_type: Callable[[str], Exception]) -> Callable[[F], F]:
    """Like wrap_exceptions(), but for generators."""

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):  # type: ignore
            with wrap_exceptions(exc_type):
                yield from fn(*args, **kwargs)

        return cast(F, wrapper)

    return decorator


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
    # TODO: this assert should fail with DBError
    assert not db.in_transaction, "foreign_keys_off must be used outside transactions"

    # TODO: this assignment should fail with DBError
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
        return "{}: {}".format(self.display_name, super().__str__())


class SchemaVersionError(DBError):
    display_name = "schema version error"


class IntegrityError(DBError):
    display_name = "integrity error"


class RequirementError(DBError):
    display_name = "database requirement error"


class IdError(DBError):
    display_name = "application id error"


db_errors = [DBError, SchemaVersionError, IntegrityError, RequirementError]


class _DBFunction(Protocol):  # pragma: no cover
    def __call__(self, db: sqlite3.Connection) -> None:
        ...


@dataclass
class NewMigration:

    # mypy will complain if we use Callable[[sqlite3.Connection], None].
    # TODO: get rid of _DBFunction when https://github.com/python/mypy/issues/5485 is resolved?
    create: _DBFunction
    version: int  # must be positive
    migrations: Dict[int, _DBFunction]
    id: int = 0

    def migrate(self, db: sqlite3.Connection) -> None:
        # pseudo-code for how the application_id is handled:
        # https://github.com/lemon24/reader/issues/211#issuecomment-778392468
        # unlike there, we allow bypassing it for testing

        with foreign_keys_off(db), ddl_transaction(db):
            if self.id:
                id = self.get_id(db)
                if id and id != self.id:
                    raise IdError(f"invalid id: 0x{id:x}")

            version = self.get_version(db)

            if not version:
                # avoid clobbering a database with application_id
                if table_count(db) != 0:
                    # TODO: maybe use a custom exception here?
                    raise DBError("database with no version already has tables")

                self.create(db)
                self.set_version(db, self.version)
                self.set_id(db, self.id)
                return

            if version == self.version:
                if self.id:
                    if not id:
                        raise IdError("database with version has missing id")
                return

            if version > self.version:
                raise SchemaVersionError(f"invalid version: {version}")

            # version < self.version

            # the actual migration code;
            #
            # might clobber a database if all of the below are true:
            #
            # * an application_id was not used from the start
            # * the database has a non-zero version which predates
            #   the migration which set application_id
            # * all of the migrations succeed

            for from_version in range(version, self.version):
                to_version = from_version + 1
                migration = self.migrations.get(from_version)
                if migration is None:
                    raise SchemaVersionError(
                        f"no migration from {from_version} to {to_version}; "
                        f"expected migrations for all versions "
                        f"later than {version}"
                    )

                self.set_version(db, to_version)
                migration(db)

                try:
                    foreign_key_check(db)
                except IntegrityError as e:
                    raise IntegrityError(
                        f"after migrating to version {to_version}: {e}"
                    ) from None

            if self.id:
                id = self.get_id(db)
                if id != self.id:
                    raise IdError(f"missing or invalid id after migration: 0x{id:x}")

    @staticmethod
    def get_version(db: sqlite3.Connection) -> int:
        return get_int_pragma(db, 'user_version')

    @staticmethod
    def set_version(db: sqlite3.Connection, version: int) -> None:
        set_int_pragma(db, 'user_version', version)

    @staticmethod
    def get_id(db: sqlite3.Connection) -> int:
        return get_int_pragma(db, 'application_id')

    @staticmethod
    def set_id(db: sqlite3.Connection, id: int) -> None:
        set_int_pragma(db, 'application_id', id)


def get_int_pragma(db: sqlite3.Connection, pragma: str) -> int:
    (value,) = db.execute(f"PRAGMA {pragma};").fetchone()
    assert isinstance(value, int), value  # for mypy
    return value


def set_int_pragma(
    db: sqlite3.Connection, pragma: str, value: int, lower_bound: int = 0
) -> None:
    if not isinstance(value, int):
        raise ValueError(f"{pragma} must be an integer, got {value!r}")
    if lower_bound is not None and value < lower_bound:
        raise ValueError(f"{pragma} must be >={lower_bound}, got {value!r}")

    db.execute(f"PRAGMA {pragma} = {value};")


def table_count(db: sqlite3.Connection) -> int:
    (value,) = db.execute("select count(*) from sqlite_master;").fetchone()
    assert isinstance(value, int), value  # for mypy
    return value


class OldMigration(NewMigration):

    # TODO: delete in 2.0

    @staticmethod
    def get_version(db: sqlite3.Connection) -> int:
        try:
            # TODO: this assignment should fail with DBError
            (version,) = db.execute("SELECT MAX(version) FROM version;").fetchone()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                return 0
            raise SchemaVersionError(f"cannot get current version: {e}") from e
        assert isinstance(version, int), version
        return version

    @classmethod
    def set_version(
        cls, db: sqlite3.Connection, version: int
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    @staticmethod
    def del_version(db: sqlite3.Connection) -> None:
        db.execute("DROP TABLE IF EXISTS version;")


class HeavyMigration(NewMigration):

    """Transition wrapper to assist with the switch from from storing
    the schema version in a "version" table to using "PRAGMA user_version".

    TODO: delete in 2.0, and rename NewMigration to HeavyMigration

    """

    def migrate(self, db: sqlite3.Connection) -> None:
        old_version = OldMigration.get_version(db)
        if old_version:
            with ddl_transaction(db):
                OldMigration.del_version(db)
                super().set_version(db, old_version)
        super().migrate(db)


def require_version(db: sqlite3.Connection, version_info: Tuple[int, ...]) -> None:
    with closing(db.cursor()) as cursor:
        # TODO: this assignment should fail with DBError
        ((version,),) = cursor.execute("SELECT sqlite_version();")

    version_ints = tuple(int(i) for i in version.split('.'))

    if version_info > version_ints:
        raise RequirementError(
            "at least SQLite version {} required, {} installed".format(
                ".".join(str(i) for i in version_info),
                ".".join(str(i) for i in sqlite3.sqlite_version_info),
            )
        )


def require_compile_options(db: sqlite3.Connection, options: Sequence[str]) -> None:
    with closing(db.cursor()) as cursor:
        actual_options = [r[0] for r in cursor.execute("PRAGMA compile_options;")]
    missing = set(options).difference(actual_options)
    if missing:
        raise RequirementError(
            f"required SQLite compile options missing: {sorted(missing)}"
        )


def setup_db(
    db: sqlite3.Connection,
    *,
    create: _DBFunction,
    version: int,
    migrations: Dict[int, _DBFunction],
    id: int,
    minimum_sqlite_version: Tuple[int, ...],
    required_sqlite_compile_options: Sequence[str] = (),
    wal_enabled: Optional[bool] = None,
) -> None:
    require_version(db, minimum_sqlite_version)
    require_compile_options(db, required_sqlite_compile_options)

    with closing(db.cursor()) as cursor:
        cursor.execute("PRAGMA foreign_keys = ON;")

        # Can't do this in a transaction, so we just do it all the time.
        #
        # Also, every cursor up to here must be closed explictly, othewise
        # we get an "cannot commit transaction - SQL statements in progress"
        # on PyPy.
        #
        # https://github.com/lemon24/reader/issues/169
        #
        if wal_enabled is not None:
            if wal_enabled:
                cursor.execute("PRAGMA journal_mode = WAL;")
            else:
                cursor.execute("PRAGMA journal_mode = DELETE;")

    migration = HeavyMigration(create, version, migrations, id)
    migration.migrate(db)


def rowcount_exactly_one(
    cursor: sqlite3.Cursor, make_exc: Callable[[], Exception]
) -> None:
    if cursor.rowcount == 0:
        raise make_exc()
    assert cursor.rowcount == 1, "shouldn't have more than 1 row"


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
            fields = ['read_count', 'write_count', 'read_bytes', 'write_bytes']
            try:
                import psutil  # type: ignore

                process = psutil.Process()
            except ImportError:
                process = None
            try:
                start_io_counters = process.io_counters()
            except AttributeError:
                pass

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
                try:
                    end_io_counters = process.io_counters()
                    data['io_counters'] = {
                        f: getattr(end_io_counters, f) - getattr(start_io_counters, f)
                        for f in fields
                    }
                except AttributeError:
                    pass

            self._log(data)

    return wrapper


@no_type_check
def _make_debug_connection_cls():  # pragma: no cover
    # we create the classes in a function to work around
    # typing.no_type_check not supporting classes (yet);
    # https://github.com/python/mypy/issues/607

    class DebugCursor(sqlite3.Cursor):
        def _log(self, data):
            # can't rely on id(self) as it's likely to be reused
            data['cursor'] = self._id
            self.connection._log(data)

        execute = _make_debug_method_wrapper(sqlite3.Cursor.execute, stmt=True)
        executemany = _make_debug_method_wrapper(sqlite3.Cursor.executemany, stmt=True)
        close = _make_debug_method_wrapper(sqlite3.Cursor.close)
        __del__ = _make_debug_method_wrapper('__del__')

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
