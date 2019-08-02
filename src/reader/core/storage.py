import contextlib
import functools
import json
import logging
import sqlite3
from datetime import datetime
from datetime import timedelta
from itertools import chain

from .exceptions import EntryNotFoundError
from .exceptions import FeedExistsError
from .exceptions import FeedNotFoundError
from .exceptions import MetadataNotFoundError
from .exceptions import StorageError
from .sqlite_utils import DBError
from .sqlite_utils import open_sqlite_db
from .types import Content
from .types import Enclosure
from .types import Entry
from .types import EntryForUpdate
from .types import Feed
from .types import FeedForUpdate

log = logging.getLogger('reader')


@contextlib.contextmanager
def wrap_storage_exceptions(*args):
    """Wrap sqlite3 exceptions in StorageError.

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
        raise StorageError("sqlite3 error") from e


def create_db(db):
    create_feeds(db)
    create_entries(db)
    create_feed_metadata(db)


def create_feeds(db):
    db.execute(
        """
        CREATE TABLE feeds (

            -- feed data
            url TEXT PRIMARY KEY NOT NULL,
            title TEXT,
            link TEXT,
            updated TIMESTAMP,
            author TEXT,
            user_title TEXT,    -- except this one, which comes from reader
            http_etag TEXT,
            http_last_modified TEXT,

            -- reader data
            stale INTEGER,
            last_updated TIMESTAMP,
            added TIMESTAMP

        );
    """
    )


def create_entries(db, name='entries'):
    # TODO: Add NOT NULL where applicable.
    db.execute(
        """
        CREATE TABLE {name} (

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

            -- reader data
            read INTEGER,
            last_updated TIMESTAMP,
            first_updated_epoch TIMESTAMP,
            feed_order INTEGER NOT NULL,

            PRIMARY KEY (id, feed),
            FOREIGN KEY (feed) REFERENCES feeds(url)
                ON UPDATE CASCADE
                ON DELETE CASCADE
        );
    """.format(
            name=name
        )
    )


def create_feed_metadata(db):
    db.execute(
        """
        CREATE TABLE feed_metadata (
            feed TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,

            PRIMARY KEY (feed, key),
            FOREIGN KEY (feed) REFERENCES feeds(url)
                ON UPDATE CASCADE
                ON DELETE CASCADE
        );
    """
    )


def update_from_10_to_11(db):  # pragma: no cover
    db.execute(
        """
        ALTER TABLE feeds
        ADD COLUMN added TIMESTAMP;
    """
    )


def update_from_11_to_12(db):  # pragma: no cover
    db.execute(
        """
        ALTER TABLE entries
        ADD COLUMN first_updated TIMESTAMP;
    """
    )


def update_from_12_to_13(db):  # pragma: no cover
    create_feed_metadata(db)


def _datetime_to_us(value):  # pragma: no cover
    if not value:
        return None
    if not isinstance(value, bytes):
        value = value.encode('utf-8')
    dt = sqlite3.converters['TIMESTAMP'](value)
    rv = int((dt - datetime(1970, 1, 1)).total_seconds() * 10 ** 6)
    return rv


def update_from_13_to_14(db):  # pragma: no cover
    db.execute(
        """
        ALTER TABLE entries
        ADD COLUMN feed_order INTEGER;
    """
    )
    db.create_function('_datetime_to_us', 1, _datetime_to_us)
    db.execute(
        """
        UPDATE entries
        SET feed_order = COALESCE(
            (SELECT _datetime_to_us(MAX(last_updated)) FROM entries)
                - _datetime_to_us(last_updated),
            0
        );
    """
    )


def update_from_14_to_15(db):  # pragma: no cover
    # https://sqlite.org/lang_altertable.html#otheralter
    db.execute("PRAGMA foreign_keys = OFF;")
    create_entries(db, 'new_entries')
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
            read,
            last_updated,
            first_updated_epoch,
            feed_order
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
            read,
            last_updated,
            first_updated,
            feed_order
        FROM entries;
    """
    )
    db.execute("DROP TABLE entries;")
    db.execute("ALTER TABLE new_entries RENAME TO entries;")
    db.execute("PRAGMA foreign_key_check;")
    db.execute("PRAGMA foreign_keys = ON;")


def open_db(path, timeout):
    return open_sqlite_db(
        path,
        create=create_db,
        version=15,
        migrations={
            # 1-9 removed before 0.1 (last in e4769d8ba77c61ec1fe2fbe99839e1826c17ace7)
            10: update_from_10_to_11,
            11: update_from_11_to_12,
            12: update_from_12_to_13,
            13: update_from_13_to_14,
            14: update_from_14_to_15,
        },
        timeout=timeout,
    )


class Storage:

    open_db = staticmethod(open_db)

    recent_threshold = timedelta(3)

    @wrap_storage_exceptions()
    def __init__(self, path=None, timeout=None):
        try:
            self.db = self.open_db(path, timeout=timeout)
        except DBError as e:
            raise StorageError(str(e)) from e
        self.path = path

    @wrap_storage_exceptions()
    def add_feed(self, url, added=None):
        with self.db:
            try:
                self.db.execute(
                    """
                    INSERT INTO feeds (url, added)
                    VALUES (:url, :added);
                """,
                    locals(),
                )
            except sqlite3.IntegrityError:
                raise FeedExistsError(url)

    @wrap_storage_exceptions()
    def remove_feed(self, url):
        with self.db:
            rows = self.db.execute(
                """
                DELETE FROM feeds
                WHERE url = :url;
            """,
                locals(),
            )
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    def _get_feeds(self, url=None, sort='title'):
        where_url_snippet = '' if not url else "WHERE url = :url"

        if sort == 'title':
            order_by_snippet = "lower(coalesce(feeds.user_title, feeds.title)) ASC"
        elif sort == 'added':
            order_by_snippet = "feeds.added DESC"
        else:
            assert False, "shouldn't get here"  # pragma: no cover

        cursor = self.db.execute(
            """
            SELECT url, updated, title, link, author, user_title FROM feeds
            {where_url_snippet}
            ORDER BY
                {order_by_snippet},
                feeds.url;
        """.format(
                **locals()
            ),
            locals(),
        )

        for row in cursor:
            yield Feed._make(row)

    @wrap_storage_exceptions()
    def get_feeds(self, url=None, sort='title'):
        return iter(list(self._get_feeds(url=url, sort=sort)))

    def _get_feeds_for_update(self, url=None, new_only=False):
        if url or new_only:
            where_snippet = "WHERE 1"
        else:
            where_snippet = ''
        where_url_snippet = '' if not url else " AND url = :url"
        where_new_only_snippet = '' if not new_only else " AND last_updated is NULL"
        cursor = self.db.execute(
            """
            SELECT url, updated, http_etag, http_last_modified, stale, last_updated FROM feeds
            {where_snippet}
            {where_url_snippet}
            {where_new_only_snippet}
            ORDER BY feeds.url;
        """.format(
                **locals()
            ),
            locals(),
        )
        for row in cursor:
            yield FeedForUpdate._make(row)

    @wrap_storage_exceptions()
    def get_feeds_for_update(self, url=None, new_only=False):
        return iter(list(self._get_feeds_for_update(url=url, new_only=new_only)))

    def _get_entry_for_update(self, feed_url, id):
        row = self.db.execute(
            """
            SELECT updated
            FROM entries
            WHERE feed = :feed_url
                AND id = :id;
        """,
            locals(),
        ).fetchone()
        if not row:
            return None
        return EntryForUpdate(row[0])

    def _get_entries_for_update_n_queries(self, entries):
        with self.db:
            return iter([self._get_entry_for_update(*e) for e in entries])

    def _get_entries_for_update_one_query(self, entries):
        if not entries:
            return []

        values_snippet = ', '.join(['(?, ?)'] * len(entries))
        parameters = list(chain.from_iterable(entries))

        rows = self.db.execute(
            """
            WITH
                input(feed, id) AS (
                    VALUES {values_snippet}
                )
                SELECT
                    entries.id IS NOT NULL,
                    entries.updated
                FROM input
                LEFT JOIN entries
                    ON (input.id, input.feed) == (entries.id, entries.feed);
        """.format(
                values_snippet=values_snippet
            ),
            parameters,
        )

        return iter(
            [EntryForUpdate(updated) if exists else None for exists, updated in rows]
        )

    @wrap_storage_exceptions()
    def get_entries_for_update(self, entries):
        entries = list(entries)
        try:
            return self._get_entries_for_update_one_query(entries)
        except sqlite3.OperationalError as e:
            if "too many SQL variables" not in str(e):
                raise
        return self._get_entries_for_update_n_queries(entries)

    @wrap_storage_exceptions()
    def set_feed_user_title(self, url, title):
        with self.db:
            rows = self.db.execute(
                """
                UPDATE feeds
                SET user_title = :title
                WHERE url = :url;
            """,
                locals(),
            )
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions()
    def mark_as_stale(self, url):
        with self.db:
            rows = self.db.execute(
                """
                UPDATE feeds
                SET stale = 1
                WHERE url = :url;
            """,
                locals(),
            )
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions()
    def mark_as_read_unread(self, feed_url, entry_id, read):
        with self.db:
            rows = self.db.execute(
                """
                UPDATE entries
                SET read = :read
                WHERE feed = :feed_url AND id = :entry_id;
            """,
                locals(),
            )
            if rows.rowcount == 0:
                raise EntryNotFoundError(feed_url, entry_id)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions()
    def update_feed(self, url, feed, http_etag, http_last_modified, last_updated):
        if feed:
            assert url == feed.url, "updating feed URL not supported"
            self._update_feed_full(
                url, feed, http_etag, http_last_modified, last_updated
            )
            return

        assert http_etag is None, "http_etag must be none if feed is none"
        assert (
            http_last_modified is None
        ), "http_last_modified must be none if feed is none"
        self._update_feed_last_updated(url, last_updated)

    def _update_feed_full(self, url, feed, http_etag, http_last_modified, last_updated):
        updated = feed.updated
        title = feed.title
        link = feed.link
        author = feed.author

        with self.db:
            rows = self.db.execute(
                """
                UPDATE feeds
                SET
                    title = :title,
                    link = :link,
                    updated = :updated,
                    author = :author,
                    http_etag = :http_etag,
                    http_last_modified = :http_last_modified,
                    stale = NULL,
                    last_updated = :last_updated
                WHERE url = :url;
            """,
                locals(),
            )

        if rows.rowcount == 0:
            raise FeedNotFoundError(url)
        assert rows.rowcount == 1, "shouldn't have more than 1 row"

    def _update_feed_last_updated(self, url, last_updated):
        with self.db:
            rows = self.db.execute(
                """
                UPDATE feeds
                SET
                    last_updated = :last_updated
                WHERE url = :url;
            """,
                locals(),
            )

        if rows.rowcount == 0:
            raise FeedNotFoundError(url)
        assert rows.rowcount == 1, "shouldn't have more than 1 row"

    def _add_or_update_entry(
        self, feed_url, entry, last_updated, first_updated_epoch, feed_order
    ):
        updated = entry.updated
        published = entry.published
        id = entry.id
        title = entry.title
        link = entry.link
        author = entry.author
        summary = entry.summary
        content = (
            json.dumps([t._asdict() for t in entry.content]) if entry.content else None
        )
        enclosures = (
            json.dumps([t._asdict() for t in entry.enclosures])
            if entry.enclosures
            else None
        )

        try:
            self.db.execute(
                """
                INSERT OR REPLACE INTO entries (
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
                    read,
                    last_updated,
                    first_updated_epoch,
                    feed_order
                ) VALUES (
                    :id,
                    :feed_url,
                    :title,
                    :link,
                    :updated,
                    :author,
                    :published,
                    :summary,
                    :content,
                    :enclosures,
                    (
                        SELECT read
                        FROM entries
                        WHERE id = :id AND feed = :feed_url
                    ),
                    :last_updated,
                    coalesce(:first_updated_epoch, (
                        SELECT first_updated_epoch
                        FROM entries
                        WHERE id = :id AND feed = :feed_url
                    )),
                    :feed_order
                );
            """,
                locals(),
            )
        except sqlite3.IntegrityError as e:
            log.debug(
                "add_entry %r of feed %r: got IntegrityError",
                entry.id,
                feed_url,
                exc_info=True,
            )
            raise FeedNotFoundError(feed_url)

    @wrap_storage_exceptions()
    def add_or_update_entries(self, entry_tuples):
        with self.db:
            for t in entry_tuples:
                self._add_or_update_entry(*t)

    def add_or_update_entry(
        self, feed_url, entry, last_updated, first_updated_epoch, feed_order
    ):
        # this is only for convenience (it's called from tests)
        self.add_or_update_entries(
            [(feed_url, entry, last_updated, first_updated_epoch, feed_order)]
        )

    def _make_get_entries_query(
        self, which, feed_url, has_enclosures, chunk_size, last, entry_id
    ):
        log.debug("_get_entries chunk_size=%s last=%s", chunk_size, last)

        if which == 'all':
            where_read_snippet = ''
        elif which == 'unread':
            where_read_snippet = """
                AND (entries.read IS NULL OR entries.read != 1)
            """
        elif which == 'read':
            where_read_snippet = """
                AND entries.read = 1
            """
        else:
            assert False, "shouldn't get here"  # pragma: no cover

        # TODO: This needs some sort of query builder so badly.

        where_next_snippet = ''
        limit_snippet = ''
        if chunk_size:
            limit_snippet = """
                LIMIT :chunk_size
            """
            if last:
                where_next_snippet = """
                    AND (
                        kinda_first_updated,
                        kinda_published,
                        feeds.url,
                        entries.last_updated,
                        negative_feed_order,
                        entries.id
                    ) < (
                        :last_entry_first_updated,
                        :last_entry_updated,
                        :last_feed_url,
                        :last_entry_last_updated,
                        :last_negative_feed_order,
                        :last_entry_id
                    )
                """

        where_feed_snippet = ''
        where_entry_snippet = ''
        if feed_url:
            where_feed_snippet = """
                AND feeds.url = :feed_url
            """
            if entry_id:
                where_entry_snippet = """
                    AND entries.id = :entry_id
                """

        where_has_enclosures_snippet = ''
        if has_enclosures is not None:
            where_has_enclosures_snippet = """
                AND {} (json_array_length(entries.enclosures) IS NULL
                        OR json_array_length(entries.enclosures) = 0)
            """.format(
                'NOT' if has_enclosures else ''
            )

        query = """
            SELECT
                feeds.url,
                feeds.updated,
                feeds.title,
                feeds.link,
                feeds.author,
                feeds.user_title,
                entries.id,
                entries.updated,
                entries.title,
                entries.link,
                entries.author,
                entries.published,
                entries.summary,
                entries.content,
                entries.enclosures,
                entries.read,
                entries.last_updated,
                coalesce(
                    CASE
                    WHEN
                        coalesce(entries.published, entries.updated) >= :recent_threshold
                        THEN entries.first_updated_epoch
                    END,
                    entries.published, entries.updated
                ) as kinda_first_updated,
                coalesce(entries.published, entries.updated) as kinda_published,
                - entries.feed_order as negative_feed_order
            FROM entries, feeds
            WHERE
                feeds.url = entries.feed
                {where_read_snippet}
                {where_feed_snippet}
                {where_entry_snippet}
                {where_next_snippet}
                {where_has_enclosures_snippet}
            ORDER BY
                kinda_first_updated DESC,
                kinda_published DESC,
                feeds.url DESC,
                entries.last_updated DESC,
                negative_feed_order DESC,
                entries.id DESC
            {limit_snippet}
            ;
        """.format(
            **locals()
        )

        log.debug("_get_entries query\n%s\n", query)

        return query

    def _get_entries(
        self, which, feed_url, has_enclosures, now, chunk_size, last, entry_id
    ):
        query = self._make_get_entries_query(
            which, feed_url, has_enclosures, chunk_size, last, entry_id
        )

        recent_threshold = now - self.recent_threshold
        if last:
            last_entry_first_updated, last_entry_updated, last_feed_url, last_entry_last_updated, last_negative_feed_order, last_entry_id = (
                last
            )

        with wrap_storage_exceptions():
            cursor = self.db.execute(query, locals())
            for t in cursor:
                feed = t[0:6]
                feed = Feed._make(feed)
                entry = t[6:13] + (
                    tuple(Content(**d) for d in json.loads(t[13])) if t[13] else (),
                    tuple(Enclosure(**d) for d in json.loads(t[14])) if t[14] else (),
                    t[15] == 1,
                    feed,
                )
                last_updated = t[16]
                first_updated_epoch = t[17]
                negative_feed_order = t[19]
                entry = Entry._make(entry)
                yield entry, (
                    first_updated_epoch or entry.published or entry.updated,
                    entry.published or entry.updated,
                    entry.feed.url,
                    last_updated,
                    negative_feed_order,
                    entry.id,
                )

    @wrap_storage_exceptions()
    def get_entries(
        self,
        which='all',
        feed_url=None,
        has_enclosures=None,
        now=None,
        chunk_size=None,
        last=None,
        entry_id=None,
    ):
        rv = self._get_entries(
            which=which,
            feed_url=feed_url,
            has_enclosures=has_enclosures,
            now=now,
            chunk_size=chunk_size,
            last=last,
            entry_id=entry_id,
        )

        if chunk_size:
            # The list() call is here to make sure callers can't block the
            # storage if they keep the result around and don't iterate over it.
            # The iter() call is here to make sure callers don't expect the
            # result to be anything more than an iterable.
            rv = iter(list(rv))

        return rv

    def _iter_feed_metadata(self, feed_url, key):
        where_url_snippet = "WHERE feed = :feed_url"
        if key is not None:
            where_url_snippet += " AND key = :key"

        cursor = self.db.execute(
            """
            SELECT key, value FROM feed_metadata
            {where_url_snippet};
        """.format(
                **locals()
            ),
            locals(),
        )

        for key, value in cursor:
            yield key, json.loads(value)

    @wrap_storage_exceptions()
    def iter_feed_metadata(self, feed_url, key=None):
        return iter(list(self._iter_feed_metadata(feed_url, key)))

    @wrap_storage_exceptions()
    def set_feed_metadata(self, feed_url, key, value):
        value = json.dumps(value)

        with self.db:
            try:
                self.db.execute(
                    """
                    INSERT OR REPLACE INTO feed_metadata (
                        feed,
                        key,
                        value
                    ) VALUES (
                        :feed_url,
                        :key,
                        :value
                    );
                """,
                    locals(),
                )
            except sqlite3.IntegrityError as e:
                raise FeedNotFoundError(feed_url)

    @wrap_storage_exceptions()
    def delete_feed_metadata(self, feed_url, key):
        with self.db:
            rows = self.db.execute(
                """
                DELETE FROM feed_metadata
                WHERE feed = :feed_url AND key = :key;
            """,
                locals(),
            )
            if rows.rowcount == 0:
                raise MetadataNotFoundError(feed_url, key)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"
