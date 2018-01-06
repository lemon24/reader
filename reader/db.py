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


VERSION = 2


class InvalidVersion(Exception):
    pass


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


def create_db(db):
    db.execute("""
        CREATE TABLE version (
            version INTEGER NOT NULL
        );
    """)
    db.execute("""
        CREATE TABLE feeds (
            url TEXT PRIMARY KEY NOT NULL,
            title TEXT,
            link TEXT,
            updated TIMESTAMP,
            http_etag TEXT,
            http_last_modified TEXT,
            stale INTEGER
        );
    """)
    db.execute("""
        CREATE TABLE entries (
            id TEXT NOT NULL,
            feed TEXT NOT NULL,
            title TEXT,
            link TEXT,
            updated TIMESTAMP,
            published TIMESTAMP,
            enclosures TEXT,
            PRIMARY KEY (id, feed),
            FOREIGN KEY (feed) REFERENCES feeds(url)
        );
    """)
    db.execute("INSERT INTO version VALUES (?);", (VERSION, ))


def update_from_1_to_2(db):
    db.execute("""
        UPDATE version
        SET version = 2;
    """)
    db.execute("""
        ALTER TABLE feeds
        ADD COLUMN stale INTEGER;
    """)


def open_db(path):
    db = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    db.execute("""
            PRAGMA foreign_keys = ON;
    """)
    with ddl_transaction(db):
        version = get_version(db)
        if version is None:
            create_db(db)
        elif version == 1:
            update_from_1_to_2(db)
        elif version != VERSION:
            raise InvalidVersion("invalid version: {}".format(version))
    return db

