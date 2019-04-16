"""
sqlite3 utilities. Contains no business logic.

"""

import sqlite3
from contextlib import contextmanager


# stolen from https://github.com/lemon24/boomtime/blob/master/boomtime/db.py

@contextmanager
def ddl_transaction(db):
    """Automatically commit/rollback transactions containing DDL statements.

    Usage:

        with ddl_transaction(db):
            db.execute(...)
            db.execute(...)

    Note: This does not work with executescript().

    Works around https://bugs.python.org/issue10740. Normally, one would
    expect to be able to use DDL statements in a transaction like so:

        with db:
            db.execute(ddl_statement)
            db.execute(other_statement)

    However, the sqlite3 transaction handling triggers an implicit commit if
    the first execute() is a DDL statement, which will prevent it from being
    rolled back if another statement following it fails.

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

    def __str__(self):
        return "{}: {}".format(self.display_name, super().__str__())

class SchemaVersionError(DBError):
    display_name = "schema version error"

class RequirementError(DBError):
    display_name = "database requirement error"

db_errors = [DBError, SchemaVersionError, RequirementError]


class HeavyMigration:

    def __init__(self, create, version, migrations):
        self.create = create
        self.version = version
        self.migrations = migrations

    @staticmethod
    def get_version(db):
        version_exists = db.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'version';
        """).fetchone() is not None
        if not version_exists:
            return None
        version, = db.execute("SELECT MAX(version) FROM version;").fetchone()
        return version

    def migrate(self, db):
        with ddl_transaction(db):
            version = self.get_version(db)

            if version is None:
                self.create(db)
                db.execute("""
                    CREATE TABLE version (
                        version INTEGER NOT NULL
                    );
                """)
                db.execute("INSERT INTO version VALUES (?);", (self.version, ))

            elif version < self.version:
                if not self.migrations.get(version):
                    raise SchemaVersionError("unsupported version: {}".format(version))

                for from_version in range(version, self.version):
                    to_version = from_version + 1
                    migration = self.migrations.get(from_version)
                    if migration is None:
                        raise SchemaVersionError(
                            "no migration from {} to {}; expected migrations for all versions "
                            "later than {}".format(from_version, to_version, version))

                    db.execute("""
                        UPDATE version
                        SET version = :to_version;
                    """, locals())
                    migration(db)

            elif version != self.version:
                raise SchemaVersionError("invalid version: {}".format(version))


def require_sqlite_version(version_info):
    if version_info > sqlite3.sqlite_version_info:
        raise RequirementError(
            "at least SQLite version {} required, {} installed".format(
                '.'.join(str(i) for i in version_info),
                '.'.join(str(i) for i in sqlite3.sqlite_version_info)
            ))


def get_db_compile_options(db):
    cursor = db.cursor()
    try:
        cursor.execute("PRAGMA compile_options;")
        return [r[0] for r in cursor.fetchall()]
    finally:
        cursor.close()


def require_sqlite_compile_options(db, options):
    missing = set(options).difference(get_db_compile_options(db))
    if missing:
        raise RequirementError(
            "required SQLite compile options missing: {}"
            .format(sorted(missing)))


def open_sqlite_db(path, *, create, version, migrations, timeout=None):
    # TODO: This is business logic, make it an argument.
    # Row value support was added in 3.15.
    require_sqlite_version((3, 15))

    kwargs = dict(detect_types=sqlite3.PARSE_DECLTYPES)
    if timeout is not None:
        kwargs['timeout'] = timeout

    db = sqlite3.connect(path, **kwargs)

    # TODO: This is business logic, make it an argument.
    # Require the JSON1 extension.
    require_sqlite_compile_options(db, ['ENABLE_JSON1'])

    # TODO: This is business logic, make it an argument.
    db.execute("""
            PRAGMA foreign_keys = ON;
    """)

    migration = HeavyMigration(create, version, migrations)
    migration.migrate(db)

    return db

