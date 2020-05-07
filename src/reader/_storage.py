import json
import logging
import sqlite3
from datetime import datetime
from datetime import timedelta
from itertools import chain
from typing import Any
from typing import cast
from typing import Iterable
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Tuple

from ._sql_utils import Query  # type: ignore
from ._sqlite_utils import DBError
from ._sqlite_utils import open_sqlite_db
from ._sqlite_utils import rowcount_exactly_one
from ._sqlite_utils import wrap_exceptions
from ._types import EntryFilterOptions
from ._types import EntryForUpdate
from ._types import EntryUpdateIntent
from ._types import FeedForUpdate
from ._types import FeedUpdateIntent
from ._utils import returns_iter_list
from .exceptions import EntryNotFoundError
from .exceptions import FeedExistsError
from .exceptions import FeedNotFoundError
from .exceptions import MetadataNotFoundError
from .exceptions import StorageError
from .types import Content
from .types import Enclosure
from .types import Entry
from .types import EntrySortOrder
from .types import Feed
from .types import FeedSortOrder
from .types import JSONType


log = logging.getLogger('reader')


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


def update_from_17_to_18(db: sqlite3.Connection) -> None:  # pragma: no cover
    # for https://github.com/lemon24/reader/issues/125
    db.execute("UPDATE feeds SET stale = 1;")


def open_db(path: str, timeout: Optional[float]) -> sqlite3.Connection:
    return open_sqlite_db(
        path,
        create=create_db,
        version=18,
        migrations={
            # 1-9 removed before 0.1 (last in e4769d8ba77c61ec1fe2fbe99839e1826c17ace7)
            # 10-16 removed before 1.0 (last in 618f158ebc0034eefb724a55a84937d21c93c1a7)
            17: update_from_17_to_18,
        },
        # Row value support was added in 3.15.
        minimum_sqlite_version=(3, 15),
        # We use the JSON1 extension for entries.content.
        required_sqlite_compile_options=["ENABLE_JSON1"],
        timeout=timeout,
    )


_GetEntriesLast = Optional[Tuple[Any, Any, Any, Any, Any, Any]]


class Storage:

    open_db = staticmethod(open_db)

    recent_threshold = timedelta(7)

    @wrap_exceptions(StorageError)
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

    @wrap_exceptions(StorageError)
    def add_feed(self, url: str, added: datetime) -> None:
        with self.db:
            try:
                self.db.execute(
                    "INSERT INTO feeds (url, added) VALUES (:url, :added);", locals(),
                )
            except sqlite3.IntegrityError:
                # FIXME: Match the error string.
                raise FeedExistsError(url)

    @wrap_exceptions(StorageError)
    def remove_feed(self, url: str) -> None:
        with self.db:
            cursor = self.db.execute("DELETE FROM feeds WHERE url = :url;", locals())
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    @returns_iter_list
    def get_feeds(
        self, url: Optional[str] = None, sort: FeedSortOrder = 'title'
    ) -> Iterable[Feed]:
        query = (
            Query()
            .SELECT("url, updated, title, link, author, user_title")
            .FROM("feeds")
        )

        if url:
            query.WHERE("url = :url")

        if sort == 'title':
            query.ORDER_BY("lower(coalesce(feeds.user_title, feeds.title)) ASC")
        elif sort == 'added':
            query.ORDER_BY("feeds.added DESC")
        else:
            assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

        # to make sure the order is deterministic
        query.ORDER_BY("feeds.url")

        for row in self.db.execute(str(query), locals()):
            yield Feed._make(row)

    @wrap_exceptions(StorageError)
    @returns_iter_list
    def get_feeds_for_update(
        self, url: Optional[str] = None, new_only: bool = False
    ) -> Iterable[FeedForUpdate]:
        query = (
            Query()
            .SELECT("url, updated, http_etag, http_last_modified, stale, last_updated")
            .FROM("feeds")
        )

        if url:
            query.WHERE("url = :url")
        if new_only:
            query.WHERE("last_updated is NULL")

        # to make sure the order is deterministic
        query.ORDER_BY("feeds.url")

        for row in self.db.execute(str(query), locals()):
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

    @wrap_exceptions(StorageError)
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

    @wrap_exceptions(StorageError)
    def set_feed_user_title(self, url: str, title: Optional[str]) -> None:
        with self.db:
            cursor = self.db.execute(
                "UPDATE feeds SET user_title = :title WHERE url = :url;", locals(),
            )
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def mark_as_stale(self, url: str) -> None:
        with self.db:
            cursor = self.db.execute(
                "UPDATE feeds SET stale = 1 WHERE url = :url;", locals(),
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
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

    @wrap_exceptions(StorageError)
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

    @wrap_exceptions(StorageError)
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

    def _make_add_or_update_entries_args(
        self, intent: EntryUpdateIntent
    ) -> Mapping[str, Any]:
        entry, last_updated, first_updated_epoch, feed_order = intent

        updated = entry.updated
        published = entry.published
        feed_url = entry.feed_url
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
        return locals()

    @wrap_exceptions(StorageError)
    def add_or_update_entries(self, entry_tuples: Iterable[EntryUpdateIntent]) -> None:

        # We need to capture the last value for exception handling
        # (it's not guaranteed all the entries belong to the same tuple).
        last_param: Mapping[str, Any] = {}

        def make_params() -> Iterable[Mapping[str, Any]]:
            nonlocal last_param
            for last_param in map(self._make_add_or_update_entries_args, entry_tuples):
                yield last_param

        with self.db:

            try:
                self.db.executemany(
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
                    make_params(),
                )
            except sqlite3.IntegrityError:
                # FIXME: Match the error string.

                feed_url = last_param['feed_url']
                entry_id = last_param['id']
                log.debug(
                    "add_entry %r of feed %r: got IntegrityError",
                    entry_id,
                    feed_url,
                    exc_info=True,
                )
                raise FeedNotFoundError(feed_url)

    def add_or_update_entry(self, intent: EntryUpdateIntent) -> None:
        # TODO: this method is for testing convenience only, maybe delete it?
        self.add_or_update_entries([intent])

    def get_entries(
        self,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        sort: EntrySortOrder = 'recent',
        chunk_size: Optional[int] = None,
        last: _GetEntriesLast = None,
    ) -> Iterable[Tuple[Entry, _GetEntriesLast]]:
        rv = self._get_entries(
            now=now,
            filter_options=filter_options,
            sort=sort,
            chunk_size=chunk_size,
            last=last,
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
        sort: EntrySortOrder,
        chunk_size: Optional[int] = None,
        last: _GetEntriesLast = None,
    ) -> Iterable[Tuple[Entry, _GetEntriesLast]]:
        query = make_get_entries_query(filter_options, sort, chunk_size, last)

        feed_url, entry_id, read, important, has_enclosures = filter_options

        recent_threshold = now - self.recent_threshold

        params = locals()
        params.update(query.last_params(last))

        with wrap_exceptions(StorageError):
            cursor = self.db.execute(str(query), params)
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
                entry = Entry._make(entry)
                rv_last = cast(_GetEntriesLast, query.extract_last(t))
                yield entry, rv_last

    @wrap_exceptions(StorageError)
    @returns_iter_list
    def iter_feed_metadata(
        self, feed_url: str, key: Optional[str] = None
    ) -> Iterable[Tuple[str, JSONType]]:
        query = (
            Query().SELECT("key, value").FROM("feed_metadata").WHERE("feed = :feed_url")
        )
        if key is not None:
            query.WHERE("key = :key")

        for mkey, value in self.db.execute(str(query), locals()):
            yield mkey, json.loads(value)

    @wrap_exceptions(StorageError)
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

    @wrap_exceptions(StorageError)
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


def make_get_entries_query(
    filter_options: EntryFilterOptions,
    sort: EntrySortOrder,
    chunk_size: Optional[int] = None,
    last: _GetEntriesLast = None,
) -> Query:
    log.debug("_get_entries chunk_size=%s last=%s", chunk_size, last)

    query = (
        Query()
        .SELECT(
            *"""
            feeds.url
            feeds.updated
            feeds.title
            feeds.link
            feeds.author
            feeds.user_title
            entries.id
            entries.updated
            entries.title
            entries.link
            entries.author
            entries.published
            entries.summary
            entries.content
            entries.enclosures
            entries.read
            entries.important
            """.split()
        )
        .FROM("entries")
        .JOIN("feeds ON feeds.url = entries.feed")
    )

    apply_filter_options(query, filter_options)

    if sort == 'recent':
        query.SELECT(
            "entries.last_updated",
            (
                "kinda_first_updated",
                """
                coalesce (
                    CASE
                    WHEN
                        coalesce(entries.published, entries.updated)
                            >= :recent_threshold
                        THEN entries.first_updated_epoch
                    END,
                    entries.published, entries.updated
                )
                """,
            ),
            ("kinda_published", "coalesce(entries.published, entries.updated)"),
            ("negative_feed_order", "- entries.feed_order"),
        )

        query.scrolling_window_order_by(
            *"""
            kinda_first_updated
            kinda_published
            feeds.url
            entries.last_updated
            negative_feed_order
            entries.id
            """.split(),
            desc=True,
        )

    elif sort == 'random':
        assert not last, last  # pragma: no cover

        # TODO: "order by random()" always goes through the full result set, which is inefficient
        # details here https://github.com/lemon24/reader/issues/105#issue-409493128
        query.ORDER_BY("random()")

    else:
        assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

    # moved here for coverage
    if chunk_size:
        query.LIMIT(":chunk_size", last=last)

    log.debug("_get_entries query\n%s\n", query)

    return query


def apply_filter_options(
    query: Query, filter_options: EntryFilterOptions, keyword: str = 'WHERE'
) -> None:
    add = getattr(query, keyword)
    feed_url, entry_id, read, important, has_enclosures = filter_options

    if feed_url:
        add("entries.feed = :feed_url")
        if entry_id:
            add("entries.id = :entry_id")

    if read is not None:
        add(f"{'' if read else 'NOT'} entries.read")

    if important is not None:
        add(f"{'' if important else 'NOT'} entries.important")

    if has_enclosures is not None:
        add(
            f"""
            {'NOT' if has_enclosures else ''}
                (json_array_length(entries.enclosures) IS NULL
                    OR json_array_length(entries.enclosures) = 0)
            """
        )
