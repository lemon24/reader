"""
sqlite3 utilities. Contains no business logic.

"""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Type

from typing_extensions import Protocol
from typing_extensions import TypedDict


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
def wrap_exceptions(exc_type: Type[Exception]) -> Iterator[None]:
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
        raise exc_type(f"sqlite3 error: {e}") from e
    except sqlite3.ProgrammingError as e:
        if "cannot operate on a closed database" in str(e).lower():
            raise exc_type(f"sqlite3 error: {e}") from e
        raise


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


db_errors = [DBError, SchemaVersionError, RequirementError]


class _DBFunction(Protocol):  # pragma: no cover
    def __call__(self, db: sqlite3.Connection) -> None:
        ...


@dataclass
class HeavyMigration:

    # mypy will complain if we use Callable[[sqlite3.Connection], None].
    # TODO: get rid of _DBFunction when https://github.com/python/mypy/issues/5485 is resolved?
    create: _DBFunction
    version: int
    migrations: Dict[int, _DBFunction]

    @staticmethod
    def get_version(db: sqlite3.Connection) -> Optional[int]:
        try:
            # TODO: this assignment should fail with DBError
            (version,) = db.execute("SELECT MAX(version) FROM version;").fetchone()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                return None
            raise
        assert isinstance(version, int)
        return version

    def migrate(self, db: sqlite3.Connection) -> None:
        with foreign_keys_off(db), ddl_transaction(db):
            version = self.get_version(db)

            if version is None:
                self.create(db)
                db.execute("CREATE TABLE version (version INTEGER NOT NULL);")
                db.execute("INSERT INTO version VALUES (?);", (self.version,))
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
                        f"later than {version}"
                    )

                db.execute("UPDATE version SET version = :to_version;", locals())
                migration(db)

                try:
                    foreign_key_check(db)
                except IntegrityError as e:
                    raise IntegrityError(
                        f"after migrating to version {to_version}: {e}"
                    ) from None


def require_sqlite_version(version_info: Tuple[int, ...]) -> None:
    if version_info > sqlite3.sqlite_version_info:
        raise RequirementError(
            "at least SQLite version {} required, {} installed".format(
                ".".join(str(i) for i in version_info),
                ".".join(str(i) for i in sqlite3.sqlite_version_info),
            )
        )


def get_db_compile_options(db: sqlite3.Connection) -> Sequence[str]:
    cursor = db.cursor()
    try:
        cursor.execute("PRAGMA compile_options;")
        return [r[0] for r in cursor.fetchall()]
    finally:
        cursor.close()


def require_sqlite_compile_options(
    db: sqlite3.Connection, options: Sequence[str]
) -> None:
    missing = set(options).difference(get_db_compile_options(db))
    if missing:
        raise RequirementError(
            f"required SQLite compile options missing: {sorted(missing)}"
        )


# Be explicit about the types of the sqlite3.connect kwargs,
# otherwise we get stuff like:
#
#   Argument 2 to "connect" has incompatible type "**Dict[str, int]"; expected "..."
#
_SqliteOptions = TypedDict(
    "_SqliteOptions", {"detect_types": int, "timeout": float}, total=False
)


def open_sqlite_db(
    path: str,
    *,
    create: _DBFunction,
    version: int,
    migrations: Dict[int, _DBFunction],
    minimum_sqlite_version: Tuple[int, ...],
    required_sqlite_compile_options: Sequence[str] = (),
    timeout: Optional[float] = None,
) -> sqlite3.Connection:
    require_sqlite_version(minimum_sqlite_version)

    kwargs: '_SqliteOptions' = dict(detect_types=sqlite3.PARSE_DECLTYPES)
    if timeout is not None:
        kwargs["timeout"] = timeout

    db = sqlite3.connect(path, **kwargs)

    try:
        require_sqlite_compile_options(db, required_sqlite_compile_options)

        db.execute("PRAGMA foreign_keys = ON;")

        migration = HeavyMigration(create, version, migrations)
        migration.migrate(db)

        return db

    except BaseException:
        db.close()
        raise


def rowcount_exactly_one(
    cursor: sqlite3.Cursor, make_exc: Callable[[], Exception]
) -> None:
    if cursor.rowcount == 0:
        raise make_exc()
    assert cursor.rowcount == 1, "shouldn't have more than 1 row"


def json_object_get(object_str: str, key: str) -> Any:
    """Extract a key from a string containing a JSON object.

    >>> json_object_get('{"k": "v"}', 'k')
    'v'

    Because of a bug in SQLite[1][2], json_extract fails for strings
    containing non-BMP characters (e.g. some emojis).

    However, when the result of json_extract is passed to a user-defined
    function, instead of failing, the function silently gets passed NULL:

    % cat bug.py
    import sqlite3, json
    db = sqlite3.connect(":memory:")
    db.create_function("udf", 1, lambda x: x)
    json_string = json.dumps("🤩")
    print(*db.execute("select udf(json_extract(?, '$'));", (json_string,)))
    print(*db.execute("select json_extract(?, '$');", (json_string,)))
    % python bug.py
    (None,)
    Traceback (most recent call last):
      File "bug.py", line 6, in <module>
        print(*db.execute("select json_extract(?, '$');", (json_string,)))
    sqlite3.OperationalError: Could not decode to UTF-8 column 'json_extract(?, '$')' with text '������'

    To work around this, we define json_object_get(value, key), equivalent
    to json_extract(value, '$.' || key), which covers our use case.

    [1]: https://www.mail-archive.com/sqlite-users@mailinglists.sqlite.org/msg117549.html
    [2]: https://bugs.python.org/issue38749

    """
    return json.loads(object_str)[key]
