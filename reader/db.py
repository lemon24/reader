import sqlite3


def create_db(db):
    with db:
        db.execute("""
            CREATE TABLE feeds (
                url TEXT PRIMARY KEY NOT NULL,
                etag TEXT,
                modified_original TEXT,
                title TEXT,
                link TEXT
            );
        """)
        db.execute("""
            CREATE TABLE entries (
                id TEXT NOT NULL,
                feed TEXT NOT NULL,
                title TEXT,
                link TEXT,
                content TEXT,
                enclosures TEXT,
                published TIMESTAMP,
                updated TIMESTAMP,
                PRIMARY KEY (id, feed),
                FOREIGN KEY (feed) REFERENCES feeds(url)
            );
        """)


def open_db(path):
    db = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    db.execute("""
            PRAGMA foreign_keys = ON;
    """)

    feeds_exists = db.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = 'feeds';
    """).fetchone() is not None

    entries_exists = db.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = 'entries';
    """).fetchone() is not None

    if not feeds_exists and not entries_exists:
        create_db(db)
    elif not feeds_exists or not entries_exists:
        raise RuntimeError("some tables missing")

    db.row_factory = sqlite3.Row

    return db

