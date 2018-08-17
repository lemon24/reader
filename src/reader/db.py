import sqlite3
from contextlib import contextmanager


# The open_db/get_version/create_db combination is intended to ease future
# database migrations; stole it from
# https://github.com/lemon24/boomtime/blob/master/boomtime/db.py


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


class InvalidVersion(Exception):
    pass


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

    def open_db(self, path):
        db = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
        db.execute("""
                PRAGMA foreign_keys = ON;
        """)
        self.setup_db(db)
        return db

    def setup_db(self, db):
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
                    raise InvalidVersion("unsupported version: {}".format(version))

                for from_version in range(version, self.version):
                    to_version = from_version + 1
                    migration = self.migrations.get(from_version)
                    if migration is None:
                        raise InvalidVersion(
                            "no migration from {} to {}; expected migrations for all versions "
                            "later than {}".format(from_version, to_version, version))

                    db.execute("""
                        UPDATE version
                        SET version = :to_version;
                    """, locals())
                    migration(db)

            elif version != self.version:
                raise InvalidVersion("invalid version: {}".format(version))


def create_db(db):
    db.execute("""
        CREATE TABLE feeds (
            url TEXT PRIMARY KEY NOT NULL,
            title TEXT,
            link TEXT,
            updated TIMESTAMP,
            author TEXT,
            user_title TEXT,
            http_etag TEXT,
            http_last_modified TEXT,
            stale INTEGER,
            last_updated TIMESTAMP
        );
    """)
    db.execute("""
        CREATE TABLE entries (
            id TEXT NOT NULL,
            feed TEXT NOT NULL,
            title TEXT,
            link TEXT,
            updated TIMESTAMP,
            author TEXT,
            published TIMESTAMP,
            summary TEXT,
            content TEXT,
            enclosures TEXT,
            read INTEGER,
            last_updated TIMESTAMP,
            PRIMARY KEY (id, feed),
            FOREIGN KEY (feed) REFERENCES feeds(url)
                ON UPDATE CASCADE
                ON DELETE CASCADE
        );
    """)


open_db = HeavyMigration(
    create=create_db,
    version=10,
    migrations={
        # 1-9 removed before 0.1 (last in e4769d8ba77c61ec1fe2fbe99839e1826c17ace7)
    },
).open_db


