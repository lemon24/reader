import json
import logging
import sqlite3
from datetime import datetime
from datetime import timedelta
from itertools import chain
from itertools import repeat
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TypeVar

from ._sql_utils import Query
from ._sqlite_utils import DBError
from ._sqlite_utils import open_sqlite_db
from ._sqlite_utils import paginated_query
from ._sqlite_utils import rowcount_exactly_one
from ._sqlite_utils import wrap_exceptions
from ._sqlite_utils import wrap_exceptions_iter
from ._types import EntryFilterOptions
from ._types import EntryForUpdate
from ._types import EntryUpdateIntent
from ._types import FeedForUpdate
from ._types import FeedUpdateIntent
from ._utils import chunks
from ._utils import join_paginated_iter
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


_T = TypeVar('_T')


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


# There are two reasons paginating methods that return an iterator:
#
# * to avoid locking the database for too long
#   (not consuming a generator should not lock the database), and
# * to avoid consuming too much memory;
#
# it is OK to take proportionally more time to get more things,
# it is not OK to have more errors.
#
# See the following for more details:
#
# https://github.com/lemon24/reader/issues/6
# https://github.com/lemon24/reader/issues/167#issuecomment-626753299


class Storage:

    open_db = staticmethod(open_db)

    recent_threshold = timedelta(7)

    @wrap_exceptions(StorageError)
    def __init__(
        self,
        path: str,
        timeout: Optional[float] = None,
        get_chunk_size: Callable[[], int] = lambda: 256,
    ):
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
        self.timeout = timeout
        # FIXME: placeholder until we have a better way of getting it from Reader, maybe
        self.get_chunk_size = get_chunk_size

    @property
    def chunk_size(self) -> int:
        return self.get_chunk_size()

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

    @wrap_exceptions_iter(StorageError)
    def get_feeds(
        self,
        url: Optional[str] = None,
        sort: FeedSortOrder = 'title',
        chunk_size: Optional[int] = None,
        last: Optional[_T] = None,
    ) -> Iterable[Tuple[Feed, Optional[_T]]]:
        query = (
            Query()
            .SELECT(*"url updated title link author user_title".split())
            .FROM("feeds")
        )

        if url:
            query.WHERE("url = :url")

        # sort by url at the end to make sure the order is deterministic
        if sort == 'title':
            query.SELECT(("kinda_title", "lower(coalesce(user_title, title))"))
            query.scrolling_window_order_by("kinda_title", "url")
        elif sort == 'added':
            query.SELECT("added")
            query.scrolling_window_order_by("added", "url", desc=True)
        else:
            assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

        yield from paginated_query(
            self.db, query, locals(), lambda t: Feed._make(t[:6]), chunk_size, last
        )

    @wrap_exceptions_iter(StorageError)
    def get_feeds_for_update(
        self, url: Optional[str] = None, new_only: bool = False,
    ) -> Iterable[FeedForUpdate]:
        # Reader shouldn't care this is paginated,
        # so we don't expose any pagination stuff.

        def inner(
            chunk_size: Optional[int], last: Optional[_T]
        ) -> Iterable[Tuple[FeedForUpdate, Optional[_T]]]:
            query = (
                Query()
                .SELECT(
                    'url',
                    'updated',
                    'http_etag',
                    'http_last_modified',
                    'stale',
                    'last_updated',
                )
                .FROM("feeds")
            )

            if url:
                query.WHERE("url = :url")
            if new_only:
                query.WHERE("last_updated is NULL")

            query.scrolling_window_order_by("url")

            yield from paginated_query(
                self.db, query, locals(), FeedForUpdate._make, chunk_size, last
            )

        yield from join_paginated_iter(inner, self.chunk_size)

    def _get_entries_for_update_n_queries(
        self, entries: Sequence[Tuple[str, str]]
    ) -> Iterable[Optional[EntryForUpdate]]:
        # We use an explicit transaction for speed
        # (otherwise we get an implicit one for each query).
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

    def _get_entries_for_update_one_query(
        self, entries: Sequence[Tuple[str, str]]
    ) -> Iterable[Optional[EntryForUpdate]]:
        if not entries:  # pragma: no cover
            return []

        values_snippet = ', '.join(repeat('(?, ?)', len(entries)))
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

        # This can't be a generator because we need to get OperationalError
        # in this function (so get_entries_for_update() below can catch it).
        return (EntryForUpdate(updated) if exists else None for exists, updated in rows)

    @wrap_exceptions_iter(StorageError)
    def get_entries_for_update(
        self, entries: Iterable[Tuple[str, str]]
    ) -> Iterable[Optional[EntryForUpdate]]:
        # It's acceptable for this method to not be atomic. TODO: Why?

        iterables = chunks(self.chunk_size, entries) if self.chunk_size else (entries,)
        for iterable in iterables:

            # The reason there are two implementations for this method:
            # https://github.com/lemon24/reader/issues/109
            iterable = list(iterable)
            try:
                rv = self._get_entries_for_update_one_query(iterable)
            except sqlite3.OperationalError as e:
                if "too many SQL variables" not in str(e):
                    raise
                rv = self._get_entries_for_update_n_queries(iterable)

            if self.chunk_size:
                rv = list(rv)
            yield from rv

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
        iterables = (
            chunks(self.chunk_size, entry_tuples)
            if self.chunk_size
            else (entry_tuples,)
        )

        # It's acceptable for this to not be atomic (only some of the entries
        # may be updated if we get an exception), since they will likely
        # be updated on the next update (because the feed will not be marked
        # as updated if there's an exception, so we get a free retry).
        for iterable in iterables:
            self._add_or_update_entries(iterable)

    def _add_or_update_entries(self, entry_tuples: Iterable[EntryUpdateIntent]) -> None:
        # We need to capture the last value for exception handling
        # (it's not guaranteed all the entries belong to the same tuple).
        # FIXME: In this case, is it ok to just fail other feeds too
        # if we have an exception? If no, we should force the entries to
        # belong to a single feed!
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

    @wrap_exceptions_iter(StorageError)
    def get_entries(
        self,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        sort: EntrySortOrder = 'recent',
        chunk_size: Optional[int] = None,
        last: Optional[_T] = None,
    ) -> Iterable[Tuple[Entry, Optional[_T]]]:

        query = make_get_entries_query(filter_options, sort)

        context = dict(
            recent_threshold=now - self.recent_threshold, **filter_options._asdict(),
        )

        def value_factory(t: Tuple[Any, ...]) -> Entry:
            feed = Feed._make(t[0:6])
            entry = t[6:13] + (
                tuple(Content(**d) for d in json.loads(t[13])) if t[13] else (),
                tuple(Enclosure(**d) for d in json.loads(t[14])) if t[14] else (),
                t[15] == 1,
                t[16] == 1,
                feed,
            )
            return Entry._make(entry)

        yield from paginated_query(
            self.db, query, context, value_factory, chunk_size, last
        )

    @wrap_exceptions_iter(StorageError)
    def iter_feed_metadata(
        self,
        feed_url: str,
        key: Optional[str] = None,
        chunk_size: Optional[int] = None,
        last: Optional[_T] = None,
    ) -> Iterable[Tuple[Tuple[str, JSONType], Optional[_T]]]:
        query = (
            Query()
            .SELECT("key", "value")
            .FROM("feed_metadata")
            .WHERE("feed = :feed_url")
        )
        if key is not None:
            query.WHERE("key = :key")

        query.scrolling_window_order_by("key")

        def value_factory(t: Tuple[Any, ...]) -> Tuple[str, JSONType]:
            key, value, *_ = t
            return key, json.loads(value)

        yield from paginated_query(
            self.db, query, locals(), value_factory, chunk_size, last
        )

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
    filter_options: EntryFilterOptions, sort: EntrySortOrder,
) -> Query:
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
        # TODO: "order by random()" always goes through the full result set, which is inefficient
        # details here https://github.com/lemon24/reader/issues/105#issue-409493128
        query.ORDER_BY("random()")

    else:
        assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

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
