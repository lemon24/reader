import sqlite3

from ._sql_utils import parse_schema
from ._sqlite_utils import ddl_transaction
from ._sqlite_utils import HeavyMigration


SCHEMA = parse_schema("""

CREATE TABLE feeds (

    -- feed data
    url TEXT PRIMARY KEY NOT NULL,
    title TEXT,
    link TEXT,
    updated TIMESTAMP,
    author TEXT,
    subtitle TEXT,
    version TEXT,
    user_title TEXT,  -- except this one, which comes from reader
    caching_info TEXT,
    data_hash BLOB,  -- derived from feed data

    -- reader data
    stale INTEGER NOT NULL DEFAULT 0,
    updates_enabled INTEGER NOT NULL DEFAULT 1,
    update_after TIMESTAMP,  -- null if the feed was never retrieved
    last_retrieved TIMESTAMP,  -- null if the feed was never retrieved
    last_updated TIMESTAMP,  -- null if the feed was never updated
    added TIMESTAMP NOT NULL,
    last_exception TEXT

    -- NOTE: when adding new fields, check if they should be set
    -- to their default value in change_feed_url()
);


CREATE TABLE entries (

    -- entry data
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
    source TEXT,
    original_feed TEXT,  -- null if the feed was never moved
    data_hash BLOB,  -- derived from entry data
    data_hash_changed INTEGER,  -- metadata about data_hash

    -- reader data
    read INTEGER,
    read_modified TIMESTAMP,
    important INTEGER,
    important_modified TIMESTAMP,
    added_by TEXT NOT NULL,
    last_updated TIMESTAMP NOT NULL,
    first_updated TIMESTAMP NOT NULL,
    first_updated_epoch TIMESTAMP NOT NULL,
    feed_order INTEGER NOT NULL,
    recent_sort TIMESTAMP NOT NULL,
    sequence BLOB,

    PRIMARY KEY (id, feed),
    FOREIGN KEY (feed) REFERENCES feeds(url)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);


CREATE TABLE global_tags (
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (key)
);

CREATE TABLE feed_tags (
    feed TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,

    PRIMARY KEY (feed, key),
    FOREIGN KEY (feed) REFERENCES feeds(url)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE TABLE entry_tags (
    id TEXT NOT NULL,
    feed TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,

    PRIMARY KEY (id, feed, key),
    FOREIGN KEY (id, feed) REFERENCES entries(id, feed)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

-- speed up get_entries() queries that use apply_recent()
CREATE INDEX entries_by_recent ON entries (
    recent_sort DESC,
    coalesce(published, updated, first_updated) DESC,
    feed DESC,
    last_updated DESC,
    - feed_order DESC,
    id DESC
);

-- speed up get_entry_counts(feed=...)
CREATE INDEX entries_by_feed ON entries (feed);

-- speed up simple get_feeds(tags=...) and get_entries(tags=...) forms
-- (see reader._storage._tags.by_key_filter docstring for details)
CREATE INDEX feed_tags_by_key ON feed_tags(key);
CREATE INDEX entry_tags_by_key ON entry_tags(key);

""")  # fmt: skip

feeds_table = SCHEMA['table']['feeds']
entries_table = SCHEMA['table']['entries']
global_tags_table = SCHEMA['table']['global_tags']
feed_tags_table = SCHEMA['table']['feed_tags']
entry_tags_table = SCHEMA['table']['entry_tags']

entries_by_recent_index = SCHEMA['index']['entries_by_recent']
entries_by_feed_index = SCHEMA['index']['entries_by_feed']
feed_tags_by_key_index = SCHEMA['index']['feed_tags_by_key']
entry_tags_by_key_index = SCHEMA['index']['entry_tags_by_key']


def create_all(db: sqlite3.Connection) -> None:
    feeds_table.create(db)
    entries_table.create(db)
    global_tags_table.create(db)
    feed_tags_table.create(db)
    entry_tags_table.create(db)
    create_indexes(db)


def create_indexes(db: sqlite3.Connection) -> None:
    entries_by_recent_index.create(db)
    entries_by_feed_index.create(db)
    feed_tags_by_key_index.create(db)
    entry_tags_by_key_index.create(db)


def update_from_36_to_37(db: sqlite3.Connection, /) -> None:  # pragma: no cover
    # for https://github.com/lemon24/reader/issues/279
    db.execute("ALTER TABLE entries ADD COLUMN recent_sort TIMESTAMP;")
    db.execute(
        """
        UPDATE entries
        SET recent_sort = coalesce(published, updated, first_updated_epoch);
        """
    )
    db.execute("DROP INDEX entries_by_kinda_first_updated;")
    db.execute("DROP INDEX entries_by_kinda_published;")
    entries_by_recent_index.create(db)


def update_from_37_to_38(db: sqlite3.Connection, /) -> None:  # pragma: no cover
    # https://github.com/lemon24/reader/issues/254#issuecomment-1404215814

    entries_table.create(db, 'new_entries')
    db.execute(
        """
        INSERT INTO new_entries (
            id,
            feed,
            title,
            link,
            updated,
            author,
            published,
            summary,
            content,
            enclosures,
            original_feed,
            data_hash,
            data_hash_changed,
            read,
            read_modified,
            important,
            important_modified,
            added_by,
            last_updated,
            first_updated,
            first_updated_epoch,
            feed_order,
            recent_sort
        )
        SELECT
            id,
            feed,
            title,
            link,
            updated,
            author,
            published,
            summary,
            content,
            enclosures,
            original_feed,
            data_hash,
            data_hash_changed,
            read,
            read_modified,
            CASE
                WHEN read AND NOT important AND important_modified is not NULL
                    THEN 0
                WHEN NOT important
                    THEN NULL
                ELSE important
            END,
            important_modified,
            added_by,
            last_updated,
            first_updated,
            first_updated_epoch,
            feed_order,
            recent_sort
        FROM entries;
        """
    )

    # IMPORTANT: this drops ALL indexes and triggers ON entries
    db.execute("DROP TABLE entries;")
    db.execute("ALTER TABLE new_entries RENAME TO entries;")

    create_indexes(db)
    # pre-3.12 (version 38), we'd re-create the entries search triggers here;
    # no point in doing that anymore, update_from_38_to_39 drops them anyway


def update_from_38_to_39(db: sqlite3.Connection, /) -> None:  # pragma: no cover
    # https://github.com/lemon24/reader/issues/323

    from ._changes import Changes
    from ._search import Search

    db.execute("ALTER TABLE entries ADD COLUMN sequence BLOB;")

    if not Search._is_enabled(db):
        return

    db.execute("DROP TABLE IF EXISTS entries_search;")
    db.execute("DROP TABLE IF EXISTS entries_search_sync_state;")
    db.execute("DROP TRIGGER IF EXISTS entries_search_entries_insert;")
    db.execute("DROP TRIGGER IF EXISTS entries_search_entries_insert_esss_exists;")
    db.execute("DROP TRIGGER IF EXISTS entries_search_entries_update;")
    db.execute("DROP TRIGGER IF EXISTS entries_search_entries_delete;")
    db.execute("DROP TRIGGER IF EXISTS entries_search_feeds_update;")
    db.execute("DROP TRIGGER IF EXISTS entries_search_feeds_update_url;")

    Changes._enable(db)

    path = db.execute(
        "SELECT file FROM pragma_database_list() WHERE name = 'main';"
    ).fetchone()[0]
    if not path:
        raise Exception("temporary databases should not need migrations")

    search_db = sqlite3.connect(path + '.search')
    try:
        Search.setup_db(search_db)
        with ddl_transaction(search_db):
            Search._disable(search_db)
            Search._enable(search_db)
    finally:
        search_db.close()


def update_from_39_to_40(db: sqlite3.Connection, /) -> None:  # pragma: no cover
    # https://github.com/lemon24/reader/issues/332
    db.execute("ALTER TABLE feeds ADD COLUMN update_after TIMESTAMP;")
    db.execute("ALTER TABLE feeds ADD COLUMN last_retrieved TIMESTAMP;")


def update_from_40_to_41(db: sqlite3.Connection, /) -> None:  # pragma: no cover
    # https://github.com/lemon24/reader/issues/307

    import json

    db.execute("ALTER TABLE feeds ADD COLUMN caching_info TEXT;")

    feeds = db.execute("SELECT url, http_etag, http_last_modified FROM feeds;")
    for url, etag, last_modified in feeds:
        caching_info = {}
        if etag:
            caching_info['etag'] = etag
        if last_modified:
            caching_info['last-modified'] = last_modified

        db.execute(
            """
            UPDATE feeds
            SET caching_info = :caching_info
            WHERE url = :url;
            """,
            {
                'url': url,
                'caching_info': json.dumps(caching_info) if caching_info else None,
            },
        )

    db.execute("ALTER TABLE feeds DROP COLUMN http_etag;")
    db.execute("ALTER TABLE feeds DROP COLUMN http_last_modified;")


def update_from_41_to_42(db: sqlite3.Connection, /) -> None:  # pragma: no cover
    # https://github.com/lemon24/reader/issues/359
    feed_tags_by_key_index.create(db)
    entry_tags_by_key_index.create(db)


def update_from_42_to_43(db: sqlite3.Connection, /) -> None:  # pragma: no cover
    # https://github.com/lemon24/reader/issues/276
    db.execute("ALTER TABLE entries ADD COLUMN source TEXT;")


VERSION = 43

MIGRATIONS = {
    # 1-9 removed before 0.1 (last in e4769d8ba77c61ec1fe2fbe99839e1826c17ace7)
    # 10-16 removed before 1.0 (last in 618f158ebc0034eefb724a55a84937d21c93c1a7)
    # 17-28 removed before 2.0 (last in be9c89581ea491d0c9cc95c9d39f073168a2fd02)
    # 29-35 removed before 3.0 (last in 69c75529a3f80107b68346d592d6450f9725187c)
    36: update_from_36_to_37,
    37: update_from_37_to_38,
    38: update_from_38_to_39,
    39: update_from_39_to_40,
    40: update_from_40_to_41,
    41: update_from_41_to_42,
    42: update_from_42_to_43,
}
MISSING_SUFFIX = (
    "; you may have skipped some required migrations, see "
    "https://reader.readthedocs.io/en/latest/changelog.html#removed-migrations-3-0"
)

MIGRATION = HeavyMigration(create_all, VERSION, MIGRATIONS, MISSING_SUFFIX)
