"""
sqlite3 utilities. Contains no business logic.

"""
import sqlite3
import sys
from contextlib import contextmanager
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import Optional
from typing import Sequence
from typing import Tuple

# TODO: remove this once we drop support for Python 3.7
if sys.version_info >= (3, 8):  # pragma: no cover
    from typing import TypedDict
else:  # pragma: no cover
    from typing_extensions import TypedDict


# initialy from https://github.com/lemon24/boomtime/blob/master/boomtime/db.py


@contextmanager
def ddl_transaction(db: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Automatically commit/rollback transactions containing DDL statements.

    Usage:

        with ddl_transaction(db):
            db.execute(...)
            db.execute(...)

    Note: This does not work with executescript().

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


class HeavyMigration:
    def __init__(
        self,
        create: Callable[[sqlite3.Connection], None],
        version: int,
        migrations: Dict[int, Callable[[sqlite3.Connection], None]],
    ):
        self.create = create
        self.version = version
        self.migrations = migrations

    @staticmethod
    def get_version(db: sqlite3.Connection) -> Optional[int]:
        version_exists = (
            db.execute(
                """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'version';
        """
            ).fetchone()
            is not None
        )
        if not version_exists:
            return None
        # TODO: this assignment should fail with DBError
        (version,) = db.execute("SELECT MAX(version) FROM version;").fetchone()
        assert isinstance(version, int)
        return version

    def migrate(self, db: sqlite3.Connection) -> None:
        # We disable foreign key checks in case any of the migrations
        # want to change the schema in ways not supported by ALTER[1].
        #
        # We have to do this because[2]:
        #
        # > It is not possible to enable or disable foreign key constraints
        # > in the middle of a multi-statement transaction [...]. Attempting
        # > to do so does not return an error; it simply has no effect.
        #
        # Note that we still do a manual check after each migration runs.
        #
        # [1]: https://sqlite.org/lang_altertable.html#otheralter
        # [2]: https://sqlite.org/foreignkeys.html#fk_enable

        # TODO: Maybe only do this if they're already on?
        db.execute("PRAGMA foreign_keys = OFF;")

        try:
            with ddl_transaction(db):
                version = self.get_version(db)

                if version is None:
                    self.create(db)
                    db.execute(
                        """
                        CREATE TABLE version (
                            version INTEGER NOT NULL
                        );
                    """
                    )
                    db.execute("INSERT INTO version VALUES (?);", (self.version,))

                elif version < self.version:
                    if not self.migrations.get(version):
                        raise SchemaVersionError(f"unsupported version: {version}")

                    for from_version in range(version, self.version):
                        to_version = from_version + 1
                        migration = self.migrations.get(from_version)
                        if migration is None:
                            raise SchemaVersionError(
                                f"no migration from {from_version} to {to_version}; "
                                f"expected migrations for all versions "
                                f"later than {version}"
                            )

                        db.execute(
                            """
                            UPDATE version
                            SET version = :to_version;
                        """,
                            locals(),
                        )
                        migration(db)

                        failed_checks = list(db.execute("PRAGMA foreign_key_check;"))
                        if failed_checks:
                            # TODO: More details regarding what failed.
                            raise IntegrityError(
                                f"after migrating to version {to_version}: "
                                "FOREIGN KEY constraint failed"
                            )

                elif version != self.version:
                    raise SchemaVersionError(f"invalid version: {version}")

        finally:
            db.execute("PRAGMA foreign_keys = ON;")


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
    create: Callable[[sqlite3.Connection], None],
    version: int,
    migrations: Dict[int, Callable[[sqlite3.Connection], None]],
    timeout: Optional[float] = None,
) -> sqlite3.Connection:
    # TODO: This is business logic, make it an argument.
    # Row value support was added in 3.15.
    require_sqlite_version((3, 15))

    kwargs: '_SqliteOptions' = dict(detect_types=sqlite3.PARSE_DECLTYPES)
    if timeout is not None:
        kwargs["timeout"] = timeout

    db = sqlite3.connect(path, **kwargs)

    try:
        # TODO: This is business logic, make it an argument.
        # Require the JSON1 extension.
        require_sqlite_compile_options(db, ["ENABLE_JSON1"])

        # TODO: This is business logic, make it an argument.
        db.execute("PRAGMA foreign_keys = ON;")

        migration = HeavyMigration(create, version, migrations)
        migration.migrate(db)

        return db

    except:
        db.close()
        raise
