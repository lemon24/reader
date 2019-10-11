import contextlib
import functools
import json
import logging
import sqlite3
from datetime import datetime
from datetime import timedelta
from itertools import chain
from typing import Any
from typing import Iterable
from typing import Optional
from typing import Tuple

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
from .types import EntryUpdateIntent
from .types import Feed
from .types import FeedForUpdate
from .types import JSONType

log = logging.getLogger('reader')


@contextlib.contextmanager
def wrap_storage_exceptions():
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
        raise StorageError(f"sqlite3 error: {e}") from e
    except sqlite3.ProgrammingError as e:
        if "cannot operate on a closed database" in str(e).lower():
            raise StorageError(f"sqlite3 error: {e}") from e
        raise


def create_db(db):
    create_feeds(db)
    create_entries(db)
    create_feed_metadata(db)


def create_feeds(db, name='feeds'):
    db.execute(
        f"""
        CREATE TABLE {name} (

            -- feed data
            url TEXT PRIMARY KEY NOT NULL,
            title TEXT,
            link TEXT,
            updated TIMESTAMP,
            author TEXT,
            user_title TEXT,  -- except this one, which comes from reader
            http_etag TEXT,
            http_last_modified TEXT,

            -- reader data
            stale INTEGER NOT NULL DEFAULT 0,
            last_updated TIMESTAMP,  -- null if the feed was never updated
            added TIMESTAMP NOT NULL

        );
    """
    )


def create_entries(db, name='entries'):
    # TODO: Add NOT NULL where applicable.
    db.execute(
        f"""
        CREATE TABLE {name} (

            -- entry data
            id TEXT NOT NULL,
            feed TEXT NOT NULL,
            title TEXT,
            link TEXT,
            updated TIMESTAMP NOT NULL,
            author TEXT,
            published TIMESTAMP,
            summary TEXT,
            content TEXT,
            enclosures TEXT,

            -- reader data
            read INTEGER NOT NULL DEFAULT 0,
            important INTEGER NOT NULL DEFAULT 0,
            last_updated TIMESTAMP NOT NULL,
            first_updated_epoch TIMESTAMP NOT NULL,
            feed_order INTEGER NOT NULL,

            PRIMARY KEY (id, feed),
            FOREIGN KEY (feed) REFERENCES feeds(url)
                ON UPDATE CASCADE
                ON DELETE CASCADE
        );
    """
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
    # Assumes foreign key checks have already been disabled.
    # https://sqlite.org/lang_altertable.html#otheralter
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


def update_from_15_to_16(db):  # pragma: no cover
    db.execute(
        """
            ALTER TABLE entries
            ADD COLUMN important INTEGER;
        """
    )


def update_from_16_to_17(db):  # pragma: no cover
    # Clean up data in-place.

    db.execute(
        """
        UPDATE feeds
        SET
            stale = COALESCE(stale, 0),
            added = COALESCE(added, '1970-01-01 00:00:00.000000')
        ;
    """
    )
    db.execute(
        """
        UPDATE entries
        SET
            read = COALESCE(read, 0),
            important = COALESCE(important, 0),
            last_updated = COALESCE(last_updated, '1970-01-01 00:00:00.000000'),
            first_updated_epoch = COALESCE(first_updated_epoch, '1970-01-01 00:00:00.000000')
        ;
    """
    )

    # Re-create tables with the new constraints;
    # assumes foreign key checks have already been disabled.
    # https://sqlite.org/lang_altertable.html#otheralter

    create_feeds(db, 'new_feeds')
    db.execute(
        """
        INSERT INTO new_feeds (
            url,
            title,
            link,
            updated,
            author,
            user_title,
            http_etag,
            http_last_modified,
            stale,
            last_updated,
            added
        )
        SELECT
            url,
            title,
            link,
            updated,
            author,
            user_title,
            http_etag,
            http_last_modified,
            stale,
            last_updated,
            added
        FROM feeds;
    """
    )
    db.execute("DROP TABLE feeds;")
    db.execute("ALTER TABLE new_feeds RENAME TO feeds;")

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
            important,
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
            important,
            last_updated,
            first_updated_epoch,
            feed_order
        FROM entries;
    """
    )
    db.execute("DROP TABLE entries;")
    db.execute("ALTER TABLE new_entries RENAME TO entries;")


def open_db(path, timeout):
    return open_sqlite_db(
        path,
        create=create_db,
        version=17,
        migrations={
            # 1-9 removed before 0.1 (last in e4769d8ba77c61ec1fe2fbe99839e1826c17ace7)
            10: update_from_10_to_11,
            11: update_from_11_to_12,
            12: update_from_12_to_13,
            13: update_from_13_to_14,
            14: update_from_14_to_15,
            15: update_from_15_to_16,
            16: update_from_16_to_17,
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

    def close(self) -> None:
        self.db.close()

    @wrap_storage_exceptions()
    def add_feed(self, url: str, added: datetime) -> None:
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
                # FIXME: Match the error string.
                raise FeedExistsError(url)

    @wrap_storage_exceptions()
    def remove_feed(self, url: str):
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
            f"""
            SELECT url, updated, title, link, author, user_title FROM feeds
            {where_url_snippet}
            ORDER BY
                {order_by_snippet},
                feeds.url;
        """,
            locals(),
        )

        for row in cursor:
            yield Feed._make(row)

    @wrap_storage_exceptions()
    def get_feeds(
        self, url: Optional[str] = None, sort: str = 'title'
    ) -> Iterable[Feed]:
        return iter(list(self._get_feeds(url=url, sort=sort)))

    def _get_feeds_for_update(self, url=None, new_only=False):
        if url or new_only:
            where_snippet = "WHERE 1"
        else:
            where_snippet = ''
        where_url_snippet = '' if not url else " AND url = :url"
        where_new_only_snippet = '' if not new_only else " AND last_updated is NULL"
        cursor = self.db.execute(
            f"""
            SELECT url, updated, http_etag, http_last_modified, stale, last_updated FROM feeds
            {where_snippet}
            {where_url_snippet}
            {where_new_only_snippet}
            ORDER BY feeds.url;
        """,
            locals(),
        )
        for row in cursor:
            yield FeedForUpdate._make(row)

    @wrap_storage_exceptions()
    def get_feeds_for_update(
        self, url: Optional[str] = None, new_only: bool = False
    ) -> Iterable[FeedForUpdate]:
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
            f"""
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
        """,
            parameters,
        )

        return iter(
            [EntryForUpdate(updated) if exists else None for exists, updated in rows]
        )

    @wrap_storage_exceptions()
    def get_entries_for_update(
        self, entries: Iterable[Tuple[str, str]]
    ) -> Iterable[EntryForUpdate]:
        entries = list(entries)
        try:
            return self._get_entries_for_update_one_query(entries)
        except sqlite3.OperationalError as e:
            if "too many SQL variables" not in str(e):
                raise
        return self._get_entries_for_update_n_queries(entries)

    @wrap_storage_exceptions()
    def set_feed_user_title(self, url: str, title: Optional[str]) -> None:
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
    def mark_as_stale(self, url: str) -> None:
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
    def mark_as_read_unread(self, feed_url: str, entry_id: str, read: bool) -> None:
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
    def mark_as_important_unimportant(
        self, feed_url: str, entry_id: str, important: bool
    ) -> None:
        with self.db:
            rows = self.db.execute(
                """
                UPDATE entries
                SET important = :important
                WHERE feed = :feed_url AND id = :entry_id;
            """,
                locals(),
            )
            if rows.rowcount == 0:
                raise EntryNotFoundError(feed_url, entry_id)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions()
    def update_feed(
        self,
        url: str,
        feed: Optional[Feed],
        http_etag: Optional[str],
        http_last_modified: Optional[str],
        last_updated: datetime,
    ):
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
                    stale = 0,
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
                    important,
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
                    (
                       SELECT important
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
            # FIXME: Match the error string.
            log.debug(
                "add_entry %r of feed %r: got IntegrityError",
                entry.id,
                feed_url,
                exc_info=True,
            )
            raise FeedNotFoundError(feed_url)

    @wrap_storage_exceptions()
    def add_or_update_entries(self, entry_tuples: Iterable[EntryUpdateIntent]) -> None:
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

    _EntryLast = Optional[Tuple[Any, Any, Any, Any, Any, Any]]

    @wrap_storage_exceptions()
    def get_entries(
        self,
        *,
        feed_url: Optional[str] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
        now: datetime,
        chunk_size: Optional[int] = None,
        last: _EntryLast = None,
        entry_id: Optional[str] = None,
    ) -> Iterable[Tuple[Entry, _EntryLast]]:
        rv = self._get_entries(
            feed_url=feed_url,
            read=read,
            important=important,
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

    def _get_entries(
        self,
        *,
        feed_url: Optional[str] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
        now: datetime,
        chunk_size: Optional[int] = None,
        last: _EntryLast = None,
        entry_id: Optional[str] = None,
    ) -> Iterable[Tuple[Entry, _EntryLast]]:
        query = self._make_get_entries_query(
            feed_url, read, important, has_enclosures, chunk_size, last, entry_id
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
                    t[16] == 1,
                    feed,
                )
                last_updated = t[17]
                first_updated_epoch = t[18]
                negative_feed_order = t[20]
                entry = Entry._make(entry)
                yield entry, (
                    first_updated_epoch or entry.published or entry.updated,
                    entry.published or entry.updated,
                    entry.feed.url,
                    last_updated,
                    negative_feed_order,
                    entry.id,
                )

    def _make_get_entries_query(
        self,
        feed_url: Optional[str] = None,
        read: Optional[bool] = None,
        important: Optional[bool] = None,
        has_enclosures: Optional[bool] = None,
        chunk_size: Optional[int] = None,
        last: _EntryLast = None,
        entry_id: Optional[str] = None,
    ) -> str:
        log.debug("_get_entries chunk_size=%s last=%s", chunk_size, last)

        where_snippets = []

        if read is not None:
            where_snippets.append(f"{'' if read else 'NOT'} entries.read")

        # TODO: This needs some sort of query builder so badly.

        limit_snippet = ''
        if chunk_size:
            limit_snippet = """
                LIMIT :chunk_size
            """
            if last:
                where_snippets.append(
                    """
                    (
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
                )

        if feed_url:
            where_snippets.append("feeds.url = :feed_url")
            if entry_id:
                where_snippets.append("entries.id = :entry_id")

        if has_enclosures is not None:
            where_snippets.append(
                f"""
                {'NOT' if has_enclosures else ''}
                    (json_array_length(entries.enclosures) IS NULL
                        OR json_array_length(entries.enclosures) = 0)
            """
            )

        if important is not None:
            where_snippets.append(f"{'' if important else 'NOT'} entries.important")

        if any(where_snippets):
            where_keyword = 'WHERE'
            where_snippet = '\n                AND '.join(where_snippets)
        else:
            where_keyword = ''
            where_snippet = ''

        query = f"""
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
                entries.important,
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
            FROM entries
            JOIN feeds ON feeds.url = entries.feed
            {where_keyword}
                {where_snippet}
            ORDER BY
                kinda_first_updated DESC,
                kinda_published DESC,
                feeds.url DESC,
                entries.last_updated DESC,
                negative_feed_order DESC,
                entries.id DESC
            {limit_snippet}
            ;
        """

        log.debug("_get_entries query\n%s\n", query)

        return query

    def _iter_feed_metadata(self, feed_url, key):
        where_url_snippet = "WHERE feed = :feed_url"
        if key is not None:
            where_url_snippet += " AND key = :key"

        cursor = self.db.execute(
            f"""
            SELECT key, value FROM feed_metadata
            {where_url_snippet};
        """,
            locals(),
        )

        for key, value in cursor:
            yield key, json.loads(value)

    @wrap_storage_exceptions()
    def iter_feed_metadata(
        self, feed_url: str, key: Optional[str] = None
    ) -> Iterable[Tuple[str, JSONType]]:
        return iter(list(self._iter_feed_metadata(feed_url, key)))

    @wrap_storage_exceptions()
    def set_feed_metadata(self, feed_url: str, key: str, value: JSONType) -> None:
        value_json = json.dumps(value)

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
                        :value_json
                    );
                """,
                    locals(),
                )
            except sqlite3.IntegrityError as e:
                # FIXME: Match the error string.
                raise FeedNotFoundError(feed_url)

    @wrap_storage_exceptions()
    def delete_feed_metadata(self, feed_url: str, key: str) -> None:
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
