import contextlib
import functools
import json
import logging
import sqlite3
from datetime import datetime
from datetime import timedelta
from itertools import chain
from typing import Any
from typing import Callable
from typing import cast
from typing import Iterable
from typing import Iterator
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union

from .exceptions import EntryNotFoundError
from .exceptions import FeedExistsError
from .exceptions import FeedNotFoundError
from .exceptions import MetadataNotFoundError
from .exceptions import StorageError
from .sqlite_utils import DBError
from .sqlite_utils import open_sqlite_db
from .sqlite_utils import rowcount_exactly_one
from .types import Content
from .types import Enclosure
from .types import Entry
from .types import EntryFilterOptions
from .types import EntryForUpdate
from .types import EntryUpdateIntent
from .types import Feed
from .types import FeedForUpdate
from .types import FeedSortOrder
from .types import FeedUpdateIntent
from .types import JSONType


log = logging.getLogger('reader')


# TODO: move wrap_storage_exceptions to sqlite_utils


@contextlib.contextmanager
def wrap_storage_exceptions(exc_type: Type[Exception] = StorageError) -> Iterator[None]:
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
        raise exc_type(f"sqlite3 error: {e}") from e
    except sqlite3.ProgrammingError as e:
        if "cannot operate on a closed database" in str(e).lower():
            raise exc_type(f"sqlite3 error: {e}") from e
        raise


FuncType = Callable[..., Any]
F = TypeVar('F', bound=FuncType)


# TODO: move returns_iter_list to utils


def returns_iter_list(fn: F) -> F:
    """Call iter(list(...)) on the return value of fn.

    The list() call makes sure callers can't block the storage
    if they keep the result around and don't iterate over it.

    The iter() call makes sure callers don't expect the
    result to be anything more than an iterable.

    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):  # type: ignore
        return iter(list(fn(*args, **kwargs)))

    return cast(F, wrapper)


def create_db(db: sqlite3.Connection) -> None:
    create_feeds(db)
    create_entries(db)
    create_feed_metadata(db)


def create_feeds(db: sqlite3.Connection, name: str = 'feeds') -> None:
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


def create_entries(db: sqlite3.Connection, name: str = 'entries') -> None:
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


def create_feed_metadata(db: sqlite3.Connection) -> None:
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


def update_from_10_to_11(db: sqlite3.Connection) -> None:  # pragma: no cover
    db.execute(
        """
        ALTER TABLE feeds
        ADD COLUMN added TIMESTAMP;
        """
    )


def update_from_11_to_12(db: sqlite3.Connection) -> None:  # pragma: no cover
    db.execute(
        """
        ALTER TABLE entries
        ADD COLUMN first_updated TIMESTAMP;
        """
    )


def update_from_12_to_13(db: sqlite3.Connection) -> None:  # pragma: no cover
    create_feed_metadata(db)


def _datetime_to_us(
    value: Optional[Union[str, bytes]]
) -> Optional[int]:  # pragma: no cover
    if not value:
        return None
    if not isinstance(value, bytes):
        value = value.encode('utf-8')
    dt = sqlite3.converters['TIMESTAMP'](value)
    rv = int((dt - datetime(1970, 1, 1)).total_seconds() * 10 ** 6)
    return rv


def update_from_13_to_14(db: sqlite3.Connection) -> None:  # pragma: no cover
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


def update_from_14_to_15(db: sqlite3.Connection) -> None:  # pragma: no cover
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


def update_from_15_to_16(db: sqlite3.Connection) -> None:  # pragma: no cover
    db.execute(
        """
        ALTER TABLE entries
        ADD COLUMN important INTEGER;
        """
    )


def update_from_16_to_17(db: sqlite3.Connection) -> None:  # pragma: no cover
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
            first_updated_epoch = COALESCE(
                first_updated_epoch,
                '1970-01-01 00:00:00.000000'
            )
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


def open_db(path: str, timeout: Optional[float]) -> sqlite3.Connection:
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
        # Row value support was added in 3.15.
        minimum_sqlite_version=(3, 15),
        # We use the JSON1 extension for entries.content.
        required_sqlite_compile_options=["ENABLE_JSON1"],
        timeout=timeout,
    )


DEFAULT_FILTER_OPTIONS = EntryFilterOptions()


# TODO: rename to _GetEntriesLast, maybe
_EntryLast = Optional[Tuple[Any, Any, Any, Any, Any, Any]]


class Storage:

    open_db = staticmethod(open_db)

    recent_threshold = timedelta(7)

    @wrap_storage_exceptions()
    def __init__(self, path: str, timeout: Optional[float] = None):
        try:
            self.db = self.open_db(path, timeout=timeout)
        except DBError as e:
            raise StorageError(str(e)) from e

        # TODO: If migrations happened, Storage-coupled Search needs to be notified.
        #
        # Even better, Search's migration should happen within the same
        # ddl_transaction open_db uses.
        #
        # Note that simply calling search.disable() and then search.enable() +
        # search.update() will probably not do the right thing, since
        # ddl_transaction is not reentrant.
        #
        # Also see "How does this interact with migrations?" in
        # https://github.com/lemon24/reader/issues/122#issuecomment-591302580

        self.path = path

    def close(self) -> None:
        self.db.close()

    @wrap_storage_exceptions()
    def add_feed(self, url: str, added: datetime) -> None:
        with self.db:
            try:
                self.db.execute(
                    "INSERT INTO feeds (url, added) VALUES (:url, :added);", locals(),
                )
            except sqlite3.IntegrityError:
                # FIXME: Match the error string.
                raise FeedExistsError(url)

    @wrap_storage_exceptions()
    def remove_feed(self, url: str) -> None:
        with self.db:
            cursor = self.db.execute("DELETE FROM feeds WHERE url = :url;", locals())
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_storage_exceptions()
    @returns_iter_list
    def get_feeds(
        self, url: Optional[str] = None, sort: FeedSortOrder = 'title'
    ) -> Iterable[Feed]:
        where_url_snippet = '' if not url else "WHERE url = :url"

        if sort == 'title':
            order_by_snippet = "lower(coalesce(feeds.user_title, feeds.title)) ASC"
        elif sort == 'added':
            order_by_snippet = "feeds.added DESC"
        else:
            assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

        cursor = self.db.execute(
            f"""
            SELECT url, updated, title, link, author, user_title FROM feeds
            {where_url_snippet}
            ORDER BY
                {order_by_snippet},
                -- to make sure the order is deterministic
                feeds.url;
            """,
            locals(),
        )

        for row in cursor:
            yield Feed._make(row)

    @wrap_storage_exceptions()
    @returns_iter_list
    def get_feeds_for_update(
        self, url: Optional[str] = None, new_only: bool = False
    ) -> Iterable[FeedForUpdate]:
        if url or new_only:
            where_snippet = "WHERE 1"
        else:
            where_snippet = ''
        where_url_snippet = '' if not url else " AND url = :url"
        where_new_only_snippet = '' if not new_only else " AND last_updated is NULL"
        cursor = self.db.execute(
            f"""
            SELECT
                url,
                updated,
                http_etag,
                http_last_modified,
                stale,
                last_updated
            FROM feeds
            {where_snippet}
            {where_url_snippet}
            {where_new_only_snippet}
            ORDER BY feeds.url;
            """,
            locals(),
        )
        for row in cursor:
            yield FeedForUpdate._make(row)

    @returns_iter_list
    def _get_entries_for_update_n_queries(
        self, entries: Sequence[Tuple[str, str]]
    ) -> Iterable[Optional[EntryForUpdate]]:
        with self.db:
            for feed_url, id in entries:  # noqa: B007
                row = self.db.execute(
                    """
                    SELECT updated
                    FROM entries
                    WHERE feed = :feed_url
                        AND id = :id;
                    """,
                    locals(),
                ).fetchone()
                yield EntryForUpdate(row[0]) if row else None

    @returns_iter_list
    def _get_entries_for_update_one_query(
        self, entries: Sequence[Tuple[str, str]]
    ) -> Iterable[Optional[EntryForUpdate]]:
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

        return (EntryForUpdate(updated) if exists else None for exists, updated in rows)

    @wrap_storage_exceptions()
    def get_entries_for_update(
        self, entries: Iterable[Tuple[str, str]]
    ) -> Iterable[Optional[EntryForUpdate]]:
        # The reason there are two implementations for this method:
        # https://github.com/lemon24/reader/issues/109

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
            cursor = self.db.execute(
                "UPDATE feeds SET user_title = :title WHERE url = :url;", locals(),
            )
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_storage_exceptions()
    def mark_as_stale(self, url: str) -> None:
        with self.db:
            cursor = self.db.execute(
                "UPDATE feeds SET stale = 1 WHERE url = :url;", locals(),
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_storage_exceptions()
    def mark_as_read_unread(self, feed_url: str, entry_id: str, read: bool) -> None:
        with self.db:
            cursor = self.db.execute(
                """
                UPDATE entries
                SET read = :read
                WHERE feed = :feed_url AND id = :entry_id;
                """,
                locals(),
            )
        rowcount_exactly_one(cursor, lambda: EntryNotFoundError(feed_url, entry_id))

    @wrap_storage_exceptions()
    def mark_as_important_unimportant(
        self, feed_url: str, entry_id: str, important: bool
    ) -> None:
        with self.db:
            cursor = self.db.execute(
                """
                UPDATE entries
                SET important = :important
                WHERE feed = :feed_url AND id = :entry_id;
                """,
                locals(),
            )
        rowcount_exactly_one(cursor, lambda: EntryNotFoundError(feed_url, entry_id))

    @wrap_storage_exceptions()
    def update_feed(self, intent: FeedUpdateIntent) -> None:
        url, last_updated, feed, http_etag, http_last_modified = intent

        if feed:
            # TODO support updating feed URL
            # https://github.com/lemon24/reader/issues/149
            assert url == feed.url, "updating feed URL not supported"

            self._update_feed_full(intent)
            return

        assert http_etag is None, "http_etag must be none if feed is none"
        assert (
            http_last_modified is None
        ), "http_last_modified must be none if feed is none"
        self._update_feed_last_updated(url, last_updated)

    def _update_feed_full(self, intent: FeedUpdateIntent) -> None:
        url, last_updated, feed, http_etag, http_last_modified = intent

        assert feed is not None
        updated = feed.updated
        title = feed.title
        link = feed.link
        author = feed.author

        with self.db:
            cursor = self.db.execute(
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

        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    def _update_feed_last_updated(self, url: str, last_updated: datetime) -> None:
        with self.db:
            cursor = self.db.execute(
                """
                UPDATE feeds
                SET
                    last_updated = :last_updated
                WHERE url = :url;
                """,
                locals(),
            )
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    def _add_or_update_entry(self, intent: EntryUpdateIntent) -> None:
        feed_url, entry, last_updated, first_updated_epoch, feed_order = intent

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
        except sqlite3.IntegrityError:
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
                self._add_or_update_entry(t)

    def add_or_update_entry(self, intent: EntryUpdateIntent) -> None:
        # TODO: this method is for testing convenience only, maybe delete it?
        self.add_or_update_entries([intent])

    def get_entries(
        self,
        now: datetime,
        filter_options: EntryFilterOptions = DEFAULT_FILTER_OPTIONS,
        chunk_size: Optional[int] = None,
        last: _EntryLast = None,
    ) -> Iterable[Tuple[Entry, _EntryLast]]:
        rv = self._get_entries(
            now=now, filter_options=filter_options, chunk_size=chunk_size, last=last
        )

        # Equivalent to using @returns_iter_list, except when we don't have
        # a chunk_size (which disables pagination, but can block the database).
        # TODO: If we don't expose chunk_size, why have this special case?
        if chunk_size:
            rv = iter(list(rv))

        return rv

    def _get_entries(
        self,
        now: datetime,
        filter_options: EntryFilterOptions,
        chunk_size: Optional[int] = None,
        last: _EntryLast = None,
    ) -> Iterable[Tuple[Entry, _EntryLast]]:
        query = self._make_get_entries_query(filter_options, chunk_size, last)

        feed_url, entry_id, read, important, has_enclosures = filter_options

        recent_threshold = now - self.recent_threshold
        if last:
            (
                last_entry_first_updated,
                last_entry_updated,
                last_feed_url,
                last_entry_last_updated,
                last_negative_feed_order,
                last_entry_id,
            ) = last

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
        filter_options: EntryFilterOptions,
        chunk_size: Optional[int] = None,
        last: _EntryLast = None,
    ) -> str:
        log.debug("_get_entries chunk_size=%s last=%s", chunk_size, last)

        feed_url, entry_id, read, important, has_enclosures = filter_options

        where_snippets = []

        if read is not None:
            where_snippets.append(f"{'' if read else 'NOT'} entries.read")

        # TODO: This needs some sort of query builder so badly.

        limit_snippet = ''
        if chunk_size:
            limit_snippet = "LIMIT :chunk_size"
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
                        coalesce(entries.published, entries.updated)
                            >= :recent_threshold
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
                -- to make sure the order is deterministic;
                -- it's unlikely it'll be used, since the probability of a feed
                -- being updated twice during the same millisecond is very low
                entries.id DESC
            {limit_snippet}
            ;
        """

        log.debug("_get_entries query\n%s\n", query)

        return query

    @wrap_storage_exceptions()
    @returns_iter_list
    def iter_feed_metadata(
        self, feed_url: str, key: Optional[str] = None
    ) -> Iterable[Tuple[str, JSONType]]:
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

        for mkey, value in cursor:
            yield mkey, json.loads(value)

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
            except sqlite3.IntegrityError:
                # FIXME: Match the error string.
                raise FeedNotFoundError(feed_url)

    @wrap_storage_exceptions()
    def delete_feed_metadata(self, feed_url: str, key: str) -> None:
        with self.db:
            cursor = self.db.execute(
                """
                DELETE FROM feed_metadata
                WHERE feed = :feed_url AND key = :key;
                """,
                locals(),
            )
        rowcount_exactly_one(cursor, lambda: MetadataNotFoundError(feed_url, key))
