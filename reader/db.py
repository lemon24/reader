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


VERSION = 5


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
            summary TEXT,
            content TEXT,
            enclosures TEXT,
            read INTEGER,
            PRIMARY KEY (id, feed),
            FOREIGN KEY (feed) REFERENCES feeds(url)
        );
    """)
    db.execute("""
        CREATE TABLE entry_tags (
            entry TEXT NOT NULL,
            feed TEXT NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (entry, feed) REFERENCES entries(id, feed),
            UNIQUE (entry, feed, tag)
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


def update_from_2_to_3(db):
    db.execute("""
        UPDATE version
        SET version = 3;
    """)
    db.execute("""
        ALTER TABLE entries
        ADD COLUMN summary TEXT;
    """)
    db.execute("""
        ALTER TABLE entries
        ADD COLUMN content TEXT;
    """)
    db.execute("""
        UPDATE feeds
        SET stale = 1;
    """)


def update_from_3_to_4(db):
    db.execute("""
        UPDATE version
        SET version = 4;
    """)
    db.execute("""
        CREATE TABLE entry_tags (
            entry TEXT NOT NULL,
            feed TEXT NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (entry, feed) REFERENCES entries(id, feed),
            UNIQUE (entry, feed, tag)
        );
    """)


def update_from_4_to_5(db):
    db.execute("""
        UPDATE version
        SET version = 5;
    """)
    db.execute("""
        ALTER TABLE entries
        ADD COLUMN read INTEGER;
    """)
    db.execute("""
        WITH tags_of_this_entry AS (
            SELECT tag
            FROM entry_tags
            WHERE entry_tags.entry = entries.id
            AND entry_tags.feed = entries.feed
        )
        UPDATE entries
        SET read = 1
        WHERE 'read' in tags_of_this_entry;
    """)
    db.execute("""
        DROP TABLE entry_tags;
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
            update_from_2_to_3(db)
            update_from_3_to_4(db)
            update_from_4_to_5(db)
        elif version == 2:
            update_from_2_to_3(db)
            update_from_3_to_4(db)
            update_from_4_to_5(db)
        elif version == 3:
            update_from_3_to_4(db)
            update_from_4_to_5(db)
        elif version == 4:
            update_from_4_to_5(db)
        elif version != VERSION:
            raise InvalidVersion("invalid version: {}".format(version))
    return db

