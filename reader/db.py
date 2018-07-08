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


VERSION = 9


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
            author TEXT,
            user_title TEXT,
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
            author TEXT,
            published TIMESTAMP,
            summary TEXT,
            content TEXT,
            enclosures TEXT,
            read INTEGER,
            PRIMARY KEY (id, feed),
            FOREIGN KEY (feed) REFERENCES feeds(url)
                ON UPDATE CASCADE
                ON DELETE CASCADE
        );
    """)
    db.execute("INSERT INTO version VALUES (?);", (VERSION, ))


def update_from_1_to_2(db):
    db.execute("""
        ALTER TABLE feeds
        ADD COLUMN stale INTEGER;
    """)


def update_from_2_to_3(db):
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


def update_from_5_to_6(db):
    db.execute("""
        ALTER TABLE entries
        RENAME TO old_entries;
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
                ON UPDATE CASCADE
                ON DELETE CASCADE
        );
    """)
    db.execute("""
        INSERT INTO entries
        SELECT
            id, feed, title, link, updated, published,
            summary, content, enclosures, read
        FROM old_entries;
    """)
    db.execute("""
        DROP TABLE old_entries;
    """)


def update_from_6_to_7(db):
    db.execute("""
        ALTER TABLE feeds
        ADD COLUMN user_title TEXT;
    """)


def update_from_7_to_8(db):
    """https://github.com/lemon24/reader/issues/46

    Drop content extra keys. Ensure enclosures 'length' is int.

    Doing this here to avoid special cases in Reader code.

    """

    import json

    cursor = db.execute("""
        SELECT id, feed, content, enclosures
        FROM entries;
    """)
    for id, feed, content_json, enclosures_json in cursor:
        if content_json is not None:
            content = []
            for data in json.loads(content_json):
                data = {k: v for k, v in data.items() if k in ('value', 'type', 'language')}
                content.append(data)
            content_json = json.dumps(content, sort_keys=True)
        if enclosures_json is not None:
            enclosures = []
            for data in json.loads(enclosures_json):
                data = {k: v for k, v in data.items() if k in ('href', 'type', 'length')}
                if 'length' in data:
                    try:
                        data['length'] = int(data['length'])
                    except (TypeError, ValueError):
                        del data['length']
                enclosures.append(data)
            enclosures_json = json.dumps(enclosures, sort_keys=True)
        db.execute("""
            UPDATE entries
            SET content = :content_json, enclosures = :enclosures_json
            WHERE id = :id and feed = :feed;
        """, locals())


def update_from_8_to_9(db):
    db.execute("""
        ALTER TABLE feeds
        ADD COLUMN author TEXT;
    """)
    db.execute("""
        ALTER TABLE entries
        ADD COLUMN author TEXT;
    """)
    db.execute("""
        UPDATE feeds
        SET stale = 1;
    """)


MIGRATIONS = {
    1: update_from_1_to_2,
    2: update_from_2_to_3,
    3: update_from_3_to_4,
    4: update_from_4_to_5,
    5: update_from_5_to_6,
    6: update_from_6_to_7,
    7: update_from_7_to_8,
    8: update_from_8_to_9,
}


def open_db(path):
    db = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    db.execute("""
            PRAGMA foreign_keys = ON;
    """)

    with ddl_transaction(db):
        version = get_version(db)

        if version is None:
            create_db(db)

        elif version < VERSION:
            if not MIGRATIONS.get(version):
                raise InvalidVersion("unsupported version: {}".format(version))

            for from_version in range(version, VERSION):
                to_version = from_version + 1
                migration = MIGRATIONS.get(from_version)
                assert migration is not None, (
                    "no migration from {} to {}; expected migrations for all versions "
                    "later than {}".format(from_version, to_version, version))

                db.execute("""
                    UPDATE version
                    SET version = :to_version;
                """, locals())
                migration(db)

        elif version != VERSION:
            raise InvalidVersion("invalid version: {}".format(version))

    return db

