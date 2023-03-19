from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from functools import partial
from typing import Any
from typing import NamedTuple
from typing import overload
from typing import TypeVar

from ._sql_utils import BaseQuery
from ._sql_utils import paginated_query
from ._sql_utils import Query
from ._sqlite_utils import DBError
from ._sqlite_utils import LocalConnectionFactory
from ._sqlite_utils import rowcount_exactly_one
from ._sqlite_utils import setup_db as setup_sqlite_db
from ._sqlite_utils import wrap_exceptions
from ._sqlite_utils import wrap_exceptions_iter
from ._types import EntryFilterOptions
from ._types import EntryForUpdate
from ._types import EntryUpdateIntent
from ._types import FeedFilterOptions
from ._types import FeedForUpdate
from ._types import FeedUpdateIntent
from ._types import TagFilter
from ._utils import chunks
from ._utils import exactly_one
from ._utils import join_paginated_iter
from ._utils import zero_or_one
from .exceptions import EntryError
from .exceptions import EntryExistsError
from .exceptions import EntryNotFoundError
from .exceptions import FeedExistsError
from .exceptions import FeedNotFoundError
from .exceptions import ReaderError
from .exceptions import StorageError
from .exceptions import TagNotFoundError
from .types import AnyResourceId
from .types import Content
from .types import Enclosure
from .types import Entry
from .types import EntryCounts
from .types import EntrySortOrder
from .types import ExceptionInfo
from .types import Feed
from .types import FeedCounts
from .types import FeedSortOrder
from .types import JSONType
from .types import MISSING
from .types import MissingType
from .types import ResourceId

APPLICATION_ID = int(''.join(f'{ord(c):x}' for c in 'read'), 16)


log = logging.getLogger('reader')


_T = TypeVar('_T')


def create_db(db: sqlite3.Connection) -> None:
    create_feeds(db)
    create_entries(db)
    create_global_tags(db)
    create_feed_tags(db)
    create_entry_tags(db)
    create_indexes(db)


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
            subtitle TEXT,
            version TEXT,
            user_title TEXT,  -- except this one, which comes from reader
            http_etag TEXT,
            http_last_modified TEXT,
            data_hash BLOB,  -- derived from feed data

            -- reader data
            stale INTEGER NOT NULL DEFAULT 0,
            updates_enabled INTEGER NOT NULL DEFAULT 1,
            last_updated TIMESTAMP,  -- null if the feed was never updated
            added TIMESTAMP NOT NULL,
            last_exception TEXT

            -- NOTE: when adding new fields, check if they should be set
            -- to their default value in change_feed_url()

        );
        """
    )


def create_entries(db: sqlite3.Connection, name: str = 'entries') -> None:
    db.execute(
        f"""
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

            PRIMARY KEY (id, feed),
            FOREIGN KEY (feed) REFERENCES feeds(url)
                ON UPDATE CASCADE
                ON DELETE CASCADE
        );
        """
    )


def create_global_tags(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE global_tags (
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (key)
        );
        """
    )


def create_feed_tags(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE feed_tags (
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


def create_entry_tags(db: sqlite3.Connection) -> None:
    db.execute(
        """
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
        """
    )


class SchemaInfo(NamedTuple):
    table_prefix: str
    id_columns: tuple[str, ...]
    not_found_exc: type[ReaderError]


SCHEMA_INFO = {
    0: SchemaInfo('global_', (), ReaderError),
    1: SchemaInfo('feed_', ('feed',), FeedNotFoundError),
    2: SchemaInfo('entry_', ('feed', 'id'), EntryNotFoundError),
}


def create_indexes(db: sqlite3.Connection) -> None:
    create_entries_by_recent_index(db)
    create_entries_by_feed_index(db)


def create_entries_by_recent_index(db: sqlite3.Connection) -> None:
    # Speed up get_entries() queries that use apply_recent().
    db.execute(
        """
        CREATE INDEX entries_by_recent ON entries(
            recent_sort DESC,
            coalesce(published, updated, first_updated) DESC,
            feed DESC,
            last_updated DESC,
            - feed_order DESC,
            id DESC
        );
        """
    )


def create_entries_by_feed_index(db: sqlite3.Connection) -> None:
    # Speed up get_entry_counts(feed=...).
    db.execute("CREATE INDEX entries_by_feed ON entries (feed);")


def update_from_36_to_37(db: sqlite3.Connection) -> None:  # pragma: no cover
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
    create_entries_by_recent_index(db)


def recreate_search_triggers(db: sqlite3.Connection) -> None:  # pragma: no cover
    from ._search import Search

    if Search._is_enabled(db):
        Search._drop_triggers(db)
        Search._create_triggers(db)


def update_from_37_to_38(db: sqlite3.Connection) -> None:  # pragma: no cover
    # https://github.com/lemon24/reader/issues/254#issuecomment-1404215814

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
    recreate_search_triggers(db)


# Row value support was added in 3.15.
# TODO: Remove the Search.update() check once this gets bumped to >=3.18.
MINIMUM_SQLITE_VERSION = (3, 15)
# We use the JSON1 extension for entries.content.
REQUIRED_SQLITE_FUNCTIONS = ['json_array_length']


def setup_db(db: sqlite3.Connection, wal_enabled: bool | None) -> None:
    return setup_sqlite_db(
        db,
        create=create_db,
        version=38,
        migrations={
            # 1-9 removed before 0.1 (last in e4769d8ba77c61ec1fe2fbe99839e1826c17ace7)
            # 10-16 removed before 1.0 (last in 618f158ebc0034eefb724a55a84937d21c93c1a7)
            # 17-28 removed before 2.0 (last in be9c89581ea491d0c9cc95c9d39f073168a2fd02)
            # 29-35 removed before 3.0 (last in 69c75529a3f80107b68346d592d6450f9725187c)
            36: update_from_36_to_37,
            37: update_from_37_to_38,
        },
        id=APPLICATION_ID,
        minimum_sqlite_version=MINIMUM_SQLITE_VERSION,
        required_sqlite_functions=REQUIRED_SQLITE_FUNCTIONS,
        wal_enabled=wal_enabled,
    )


# There are two reasons for paginating methods that return an iterator:
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

# When trying to fix "database is locked" errors or to optimize stuff,
# have a look at the lessons here first:
# https://github.com/lemon24/reader/issues/175#issuecomment-657495233

# When adding a new method, add a new test_storage.py::test_errors_locked test.


MISSING_MIGRATION_DETAIL = (
    "; you may have skipped some required migrations, see "
    "https://reader.readthedocs.io/en/latest/changelog.html#removed-migrations-3-0"
)


class Storage:
    """Data access object used for all storage except search."""

    # chunk_size and entry_counts_average_periods
    # are not part of the Storage interface,
    # but are part of the private API of this implementation.
    chunk_size = 2**8
    # 1, 3, 12 months rounded down to days,
    # assuming an average of 30.436875 days/month
    entry_counts_average_periods = (30, 91, 365)

    @wrap_exceptions(StorageError)
    def __init__(
        self,
        path: str,
        timeout: float | None = None,
        wal_enabled: bool | None = True,
        factory: type[sqlite3.Connection] | None = None,
    ):
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs['timeout'] = timeout
        if factory:  # pragma: no cover
            kwargs['factory'] = factory

        with wrap_exceptions(StorageError, "error while opening database"):
            self.factory = LocalConnectionFactory(
                path,
                detect_types=sqlite3.PARSE_DECLTYPES,
                **kwargs,
            )
            db = self.factory()

        with wrap_exceptions(StorageError, "error while setting up database"):
            try:
                try:
                    self.setup_db(db, wal_enabled)
                except BaseException:
                    db.close()
                    raise
            except DBError as e:
                message = str(e)
                if 'no migration' in message:
                    message += MISSING_MIGRATION_DETAIL
                raise StorageError(message=message) from None

        self.path = path
        self.timeout = timeout

    def get_db(self) -> sqlite3.Connection:
        # Not part of the Storage API to Reader.
        # Used internally.
        try:
            return self.factory()
        except DBError as e:
            raise StorageError(message=str(e)) from None

    # Not part of the Storage API to Reader.
    # Used for testing.
    setup_db = staticmethod(setup_db)

    @wrap_exceptions(StorageError)
    def __enter__(self) -> None:
        try:
            self.factory.__enter__()
        except DBError as e:
            raise StorageError(message=str(e)) from None

    @wrap_exceptions(StorageError)
    def __exit__(self, *_: Any) -> None:
        self.factory.__exit__()

    @wrap_exceptions(StorageError)
    def close(self) -> None:
        self.factory.close()

    @wrap_exceptions(StorageError)
    def add_feed(self, url: str, added: datetime) -> None:
        with self.get_db() as db:
            try:
                db.execute(
                    "INSERT INTO feeds (url, added) VALUES (:url, :added);",
                    dict(url=url, added=added),
                )
            except sqlite3.IntegrityError as e:
                if "unique constraint failed" not in str(e).lower():  # pragma: no cover
                    raise
                raise FeedExistsError(url) from None

    @wrap_exceptions(StorageError)
    def delete_feed(self, url: str) -> None:
        with self.get_db() as db:
            cursor = db.execute("DELETE FROM feeds WHERE url = :url;", dict(url=url))
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def change_feed_url(self, old: str, new: str) -> None:
        with self.get_db() as db:
            try:
                cursor = db.execute(
                    "UPDATE feeds SET url = :new WHERE url = :old;",
                    dict(old=old, new=new),
                )
            except sqlite3.IntegrityError as e:
                if "unique constraint failed" not in str(e).lower():  # pragma: no cover
                    raise
                raise FeedExistsError(new) from None
            else:
                rowcount_exactly_one(cursor, lambda: FeedNotFoundError(old))

            # Some of the fields are not kept from the old feed; details:
            # https://github.com/lemon24/reader/issues/149#issuecomment-700532183
            db.execute(
                """
                UPDATE feeds
                SET
                    updated = NULL,
                    version = NULL,
                    http_etag = NULL,
                    http_last_modified = NULL,
                    stale = 0,
                    last_updated = NULL,
                    last_exception = NULL
                WHERE url = ?;
                """,
                (new,),
            )

            db.execute(
                """
                UPDATE entries
                SET original_feed = (
                    SELECT coalesce(sub.original_feed, :old)
                    FROM entries AS sub
                    WHERE entries.id = sub.id AND entries.feed = sub.feed
                )
                WHERE feed = :new;
                """,
                dict(old=old, new=new),
            )

    def get_feeds(
        self,
        filter_options: FeedFilterOptions = FeedFilterOptions(),  # noqa: B008
        sort: FeedSortOrder = 'title',
        limit: int | None = None,
        starting_after: str | None = None,
    ) -> Iterable[Feed]:
        rv = join_paginated_iter(
            partial(self.get_feeds_page, filter_options, sort),  # type: ignore[arg-type]
            self.chunk_size,
            self.get_feed_last(sort, starting_after) if starting_after else None,
            limit or 0,
        )
        yield from rv

    @wrap_exceptions(StorageError)
    def get_feed_last(self, sort: str, url: str) -> tuple[Any, ...]:
        # TODO: make this method private?

        query = Query().FROM("feeds").WHERE("url = :url")

        # TODO: kinda sorta duplicates the scrolling_window_order_by call
        if sort == 'title':
            query.SELECT(("kinda_title", "lower(coalesce(user_title, title))"), 'url')
        elif sort == 'added':
            query.SELECT("added", 'url')
        else:
            assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

        return zero_or_one(
            self.get_db().execute(str(query), dict(url=url)),
            lambda: FeedNotFoundError(url),
        )

    @wrap_exceptions_iter(StorageError)
    def get_feeds_page(
        self,
        filter_options: FeedFilterOptions = FeedFilterOptions(),  # noqa: B008
        sort: FeedSortOrder = 'title',
        chunk_size: int | None = None,
        last: _T | None = None,
    ) -> Iterable[tuple[Feed, _T | None]]:
        query, context = make_get_feeds_query(filter_options, sort)
        yield from paginated_query(
            self.get_db(), query, context, chunk_size, last, feed_factory
        )

    @wrap_exceptions(StorageError)
    def get_feed_counts(
        self,
        filter_options: FeedFilterOptions = FeedFilterOptions(),  # noqa: B008
    ) -> FeedCounts:
        query = (
            Query()
            .SELECT(
                'count(*)',
                'coalesce(sum(last_exception IS NOT NULL), 0)',
                'coalesce(sum(updates_enabled == 1), 0)',
            )
            .FROM("feeds")
        )

        context = apply_feed_filter_options(query, filter_options)

        row = exactly_one(self.get_db().execute(str(query), context))

        return FeedCounts(*row)

    @wrap_exceptions_iter(StorageError)
    def get_feeds_for_update(
        self,
        filter_options: FeedFilterOptions = FeedFilterOptions(),  # noqa: B008
    ) -> Iterable[FeedForUpdate]:
        # Reader shouldn't care this is paginated,
        # so we don't expose any pagination stuff.

        def inner(
            chunk_size: int | None, last: _T | None
        ) -> Iterable[tuple[FeedForUpdate, _T | None]]:
            query = (
                Query()
                .SELECT(
                    'url',
                    'updated',
                    'http_etag',
                    'http_last_modified',
                    'stale',
                    'last_updated',
                    ('last_exception', 'last_exception IS NOT NULL'),
                    'data_hash',
                )
                .FROM("feeds")
            )

            # TODO: stale and last_exception should be bool, not int

            context = apply_feed_filter_options(query, filter_options)

            query.scrolling_window_order_by("url")

            yield from paginated_query(
                self.get_db(), query, context, chunk_size, last, FeedForUpdate._make
            )

        yield from join_paginated_iter(inner, self.chunk_size)

    def _get_entries_for_update(
        self, entries: Iterable[tuple[str, str]]
    ) -> Iterable[EntryForUpdate | None]:
        # We could fetch everything in a single query,
        # but there are limits to the number of variables used in a query,
        # and we'd have to fall back to this anyway.
        # This is only ~10% slower than the single query version.
        # Single query version last in e39b0134cb3a2fe2bb346d42355a764181926a82.

        # This can't be a generator;
        # we must get the result inside the transaction, otherwise we get:
        #   Cursor needed to be reset because of commit/rollback
        #   and can no longer be fetched from.
        rv = []

        with self.get_db() as db:
            # We use an explicit transaction for speed,
            # otherwise we get an implicit one for each query).
            db.execute('BEGIN;')

            for feed_url, id in entries:  # noqa: B007
                context = dict(feed_url=feed_url, id=id)
                row = db.execute(
                    """
                    SELECT
                        updated,
                        published,
                        data_hash,
                        data_hash_changed
                    FROM entries
                    WHERE feed = :feed_url
                        AND id = :id;
                    """,
                    context,
                ).fetchone()
                rv.append(EntryForUpdate._make(row) if row else None)

        return rv

    @wrap_exceptions_iter(StorageError)
    def get_entries_for_update(
        self, entries: Iterable[tuple[str, str]]
    ) -> Iterable[EntryForUpdate | None]:
        # It's acceptable for this method to not be atomic. TODO: Why?

        iterables = chunks(self.chunk_size, entries) if self.chunk_size else (entries,)

        for iterable in iterables:
            rv = self._get_entries_for_update(iterable)
            if self.chunk_size:
                rv = list(rv)
            yield from rv

    @wrap_exceptions(StorageError)
    def set_feed_user_title(self, url: str, title: str | None) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                "UPDATE feeds SET user_title = :title WHERE url = :url;",
                dict(url=url, title=title),
            )
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def set_feed_updates_enabled(self, url: str, enabled: bool) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                "UPDATE feeds SET updates_enabled = :updates_enabled WHERE url = :url;",
                dict(url=url, updates_enabled=enabled),
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def mark_as_stale(self, url: str) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                "UPDATE feeds SET stale = 1 WHERE url = :url;", dict(url=url)
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def mark_as_read(
        self, feed_url: str, entry_id: str, read: bool, modified: datetime | None
    ) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                """
                UPDATE entries
                SET
                    read = :read,
                    read_modified = :modified
                WHERE feed = :feed_url AND id = :entry_id;
                """,
                dict(
                    feed_url=feed_url, entry_id=entry_id, read=read, modified=modified
                ),
            )
        rowcount_exactly_one(cursor, lambda: EntryNotFoundError(feed_url, entry_id))

    @wrap_exceptions(StorageError)
    def mark_as_important(
        self,
        feed_url: str,
        entry_id: str,
        important: bool | None,
        modified: datetime | None,
    ) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                """
                UPDATE entries
                SET
                    important = :important,
                    important_modified = :modified
                WHERE feed = :feed_url AND id = :entry_id;
                """,
                dict(
                    feed_url=feed_url,
                    entry_id=entry_id,
                    important=important,
                    modified=modified,
                ),
            )
        rowcount_exactly_one(cursor, lambda: EntryNotFoundError(feed_url, entry_id))

    # TODO: (maybe) unified pair of methods to get/set "hidden" entry attributes

    @wrap_exceptions(StorageError)
    def get_entry_recent_sort(self, entry: tuple[str, str]) -> datetime:
        feed_url, entry_id = entry
        rows = self.get_db().execute(
            """
            SELECT recent_sort
            FROM entries
            WHERE feed = :feed_url AND id = :entry_id;
            """,
            dict(feed_url=feed_url, entry_id=entry_id),
        )
        return zero_or_one(
            (r[0] for r in rows), lambda: EntryNotFoundError(feed_url, entry_id)
        )

    @wrap_exceptions(StorageError)
    def set_entry_recent_sort(
        self, entry: tuple[str, str], recent_sort: datetime
    ) -> None:
        feed_url, entry_id = entry
        with self.get_db() as db:
            cursor = db.execute(
                """
                UPDATE entries
                SET
                    recent_sort = :recent_sort
                WHERE feed = :feed_url AND id = :entry_id;
                """,
                dict(feed_url=feed_url, entry_id=entry_id, recent_sort=recent_sort),
            )
        rowcount_exactly_one(cursor, lambda: EntryNotFoundError(feed_url, entry_id))

    @wrap_exceptions(StorageError)
    def update_feed(self, intent: FeedUpdateIntent) -> None:
        url, last_updated, feed, http_etag, http_last_modified, last_exception = intent

        if feed:
            # TODO support updating feed URL
            # https://github.com/lemon24/reader/issues/149
            assert url == feed.url, "updating feed URL not supported"

            assert last_exception is None, "last_exception must be none if feed is set"

            self._update_feed_full(intent)
            return

        assert http_etag is None, "http_etag must be none if feed is none"
        assert (
            http_last_modified is None
        ), "http_last_modified must be none if feed is none"

        if not last_exception:
            assert last_updated, "last_updated must be set if last_exception is none"
            self._update_feed_last_updated(url, last_updated)
        else:
            assert (
                not last_updated
            ), "last_updated must not be set if last_exception is not none"
            self._update_feed_last_exception(url, last_exception)

    def _update_feed_full(self, intent: FeedUpdateIntent) -> None:
        context = intent._asdict()
        feed = context.pop('feed')
        assert feed is not None
        context.pop('last_exception')

        context.update(feed._asdict(), data_hash=feed.hash)

        with self.get_db() as db:
            cursor = db.execute(
                """
                UPDATE feeds
                SET
                    title = :title,
                    link = :link,
                    updated = :updated,
                    author = :author,
                    subtitle = :subtitle,
                    version = :version,
                    http_etag = :http_etag,
                    http_last_modified = :http_last_modified,
                    data_hash = :data_hash,
                    stale = 0,
                    last_updated = :last_updated,
                    last_exception = NULL
                WHERE url = :url;
                """,
                context,
            )

        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(intent.url))

    def _update_feed_last_updated(self, url: str, last_updated: datetime) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                """
                UPDATE feeds
                SET
                    last_updated = :last_updated,
                    last_exception = NULL
                WHERE url = :url;
                """,
                dict(url=url, last_updated=last_updated),
            )
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    def _update_feed_last_exception(
        self, url: str, last_exception: ExceptionInfo
    ) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                """
                UPDATE feeds
                SET
                    last_exception = :last_exception
                WHERE url = :url;
                """,
                dict(url=url, last_exception=json.dumps(last_exception._asdict())),
            )
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

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

    def _add_or_update_entries(
        self, intents: Iterable[EntryUpdateIntent], exclusive: bool = False
    ) -> None:
        query = f"""
            INSERT {'OR ABORT' if exclusive else 'OR REPLACE'} INTO entries (
                id,
                feed,
                --
                title,
                link,
                updated,
                author,
                published,
                summary,
                content,
                enclosures,
                read,
                read_modified,
                important,
                important_modified,
                last_updated,
                first_updated,
                first_updated_epoch,
                feed_order,
                recent_sort,
                original_feed,
                data_hash,
                data_hash_changed,
                added_by
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
                coalesce((
                    SELECT read
                    FROM entries
                    WHERE id = :id AND feed = :feed_url
                ), 0),
                (
                    SELECT read_modified
                    FROM entries
                    WHERE id = :id AND feed = :feed_url
                ),
                (
                    SELECT important
                    FROM entries
                    WHERE id = :id AND feed = :feed_url
                ),
                (
                    SELECT important_modified
                    FROM entries
                    WHERE id = :id AND feed = :feed_url
                ),
                :last_updated,
                coalesce(:first_updated, (
                    SELECT first_updated
                    FROM entries
                    WHERE id = :id AND feed = :feed_url
                )),
                coalesce(:first_updated_epoch, (
                    SELECT first_updated_epoch
                    FROM entries
                    WHERE id = :id AND feed = :feed_url
                )),
                :feed_order,
                coalesce(:recent_sort, (
                    SELECT recent_sort
                    FROM entries
                    WHERE id = :id AND feed = :feed_url
                )),
                NULL, -- original_feed
                :data_hash,
                :data_hash_changed,
                :added_by
            );
        """

        with self.get_db() as db:
            try:
                # we could use executemany(), but it's not noticeably faster
                for intent in intents:
                    db.execute(query, entry_update_intent_to_dict(intent))

            except sqlite3.IntegrityError as e:
                e_msg = str(e).lower()
                feed_url, entry_id = intent.entry.resource_id

                log.debug(
                    "add_entry %r of feed %r: got IntegrityError",
                    entry_id,
                    feed_url,
                    exc_info=True,
                )

                if "foreign key constraint failed" in e_msg:
                    raise FeedNotFoundError(feed_url) from None

                elif "unique constraint failed: entries.id, entries.feed" in e_msg:
                    raise EntryExistsError(feed_url, entry_id) from None

                else:  # pragma: no cover
                    raise

    def add_or_update_entry(self, intent: EntryUpdateIntent) -> None:
        # TODO: this method is for testing convenience only, maybe delete it?
        self.add_or_update_entries([intent])

    @wrap_exceptions(StorageError)
    def add_entry(self, intent: EntryUpdateIntent) -> None:
        # TODO: unify with the or_update variants
        self._add_or_update_entries([intent], exclusive=True)

    @wrap_exceptions(StorageError)
    def delete_entries(
        self, entries: Iterable[tuple[str, str]], *, added_by: str | None = None
    ) -> None:
        r"""Delete a list of entries.

        Args:
            entries (list(tuple(str, str))):
                A list of :attr:`~reader.Entry.resource_id`\s.
            added_by (str or None):
                If given, only delete the entries if their
                :attr:`~reader.Entry.added_by` is equal to this.

        Raises:
            EntryNotFoundError: An entry does not exist.
            EntryError: An entry has a different ``added_by`` from the given one.

        """
        # This must be atomic (unlike add_or_update_entries()); hence, no paging.
        # We'll deal with locking issues only if they start appearing
        # (hopefully, there are both fewer entries to be deleted and
        # this takes less time per entry).

        delete_query = "DELETE FROM entries WHERE feed = :feed AND id = :id"
        added_by_query = "SELECT added_by FROM entries WHERE feed = :feed AND id = :id"

        with self.get_db() as db:
            cursor = db.cursor()

            for feed_url, entry_id in entries:
                context = dict(feed=feed_url, id=entry_id)

                if added_by is not None:
                    row = cursor.execute(added_by_query, context).fetchone()
                    if row:
                        if row[0] != added_by:
                            raise EntryError(
                                feed_url,
                                entry_id,
                                f"entry must be added by {added_by!r}, got {row[0]!r}",
                            )

                cursor.execute(delete_query, context)
                rowcount_exactly_one(
                    cursor, lambda: EntryNotFoundError(feed_url, entry_id)  # noqa: B023
                )

    def get_entries(
        self,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        sort: EntrySortOrder = 'recent',
        limit: int | None = None,
        starting_after: tuple[str, str] | None = None,
    ) -> Iterable[Entry]:
        # TODO: deduplicate
        if sort == 'recent':
            rv = join_paginated_iter(
                partial(self.get_entries_page, now, filter_options, sort),  # type: ignore[arg-type]
                self.chunk_size,
                self.get_entry_last(now, sort, starting_after)
                if starting_after
                else None,
                limit or 0,
            )
        elif sort == 'random':
            assert not starting_after
            it = self.get_entries_page(
                now,
                filter_options,
                sort,
                min(limit, self.chunk_size or limit) if limit else self.chunk_size,
            )
            rv = (entry for entry, _ in it)
        else:
            assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

        yield from rv

    @wrap_exceptions(StorageError)
    def get_entry_last(
        self, now: datetime, sort: str, entry: tuple[str, str]
    ) -> tuple[Any, ...]:
        # TODO: make this method private?

        feed_url, entry_id = entry

        query = Query().FROM("entries").WHERE("feed = :feed AND id = :id")

        assert sort != 'random'

        # TODO: kinda sorta duplicates the scrolling_window_order_by call
        if sort == 'recent':
            query.SELECT(*make_recent_last_select())
        else:
            assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

        context = dict(feed=feed_url, id=entry_id)

        return zero_or_one(
            self.get_db().execute(str(query), context),
            lambda: EntryNotFoundError(feed_url, entry_id),
        )

    @wrap_exceptions_iter(StorageError)
    def get_entries_page(
        self,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        sort: EntrySortOrder = 'recent',
        chunk_size: int | None = None,
        last: _T | None = None,
    ) -> Iterable[tuple[Entry, _T | None]]:
        query, context = make_get_entries_query(filter_options, sort)
        yield from paginated_query(
            self.get_db(), query, context, chunk_size, last, entry_factory
        )

    @wrap_exceptions(StorageError)
    def get_entry_counts(
        self,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
    ) -> EntryCounts:

        entries_query = Query().SELECT('id', 'feed').FROM('entries')
        context = apply_entry_filter_options(entries_query, filter_options)

        query, new_context = make_entry_counts_query(
            now, self.entry_counts_average_periods, entries_query
        )
        context.update(new_context)

        row = exactly_one(self.get_db().execute(str(query), context))

        return EntryCounts(*row[:4], row[4:7])  # type: ignore[call-arg]

    def get_tags(
        self,
        resource_id: AnyResourceId,
        key: str | None = None,
    ) -> Iterable[tuple[str, JSONType]]:
        yield from join_paginated_iter(
            partial(self.get_tags_page, resource_id, key),
            self.chunk_size,
        )

    @wrap_exceptions_iter(StorageError)
    def get_tags_page(
        self,
        resource_id: AnyResourceId,
        key: str | None = None,
        chunk_size: int | None = None,
        last: _T | None = None,
    ) -> Iterable[tuple[tuple[str, JSONType], _T | None]]:
        query = Query().SELECT("key")
        context: dict[str, Any] = dict()

        if resource_id is not None:
            info = SCHEMA_INFO[len(resource_id)]
            query.FROM(f"{info.table_prefix}tags")

            if not any(p is None for p in resource_id):
                query.SELECT("value")
                for column in info.id_columns:
                    query.WHERE(f"{column} = :{column}")
                context.update(zip(info.id_columns, resource_id))
            else:
                query.SELECT_DISTINCT("'null'")

        else:
            union = '\nUNION\n'.join(
                f"SELECT key, value FROM {i.table_prefix}tags"
                for i in SCHEMA_INFO.values()
            )
            query.WITH(('tags', union)).FROM('tags')
            query.SELECT_DISTINCT("'null'")

        if key is not None:
            query.WHERE("key = :key")
            context.update(key=key)

        query.scrolling_window_order_by("key")

        def row_factory(t: tuple[Any, ...]) -> tuple[str, JSONType]:
            key, value, *_ = t
            return key, json.loads(value)

        yield from paginated_query(
            self.get_db(), query, context, chunk_size, last, row_factory
        )

    @overload
    def set_tag(self, resource_id: ResourceId, key: str) -> None:  # pragma: no cover
        ...

    @overload
    def set_tag(
        self, resource_id: ResourceId, key: str, value: JSONType
    ) -> None:  # pragma: no cover
        ...

    @wrap_exceptions(StorageError)
    def set_tag(
        self,
        resource_id: ResourceId,
        key: str,
        value: MissingType | JSONType = MISSING,
    ) -> None:
        info = SCHEMA_INFO[len(resource_id)]

        params = dict(zip(info.id_columns, resource_id), key=key)

        id_columns = info.id_columns + ('key',)
        id_columns_str = ', '.join(id_columns)
        id_values_str = ', '.join(f':{c}' for c in id_columns)

        if value is not MISSING:
            value_str = ':value'
            params.update(value=json.dumps(value))
        else:
            value_str = f"""
                coalesce((
                    SELECT value FROM {info.table_prefix}tags
                    WHERE (
                        {id_columns_str}
                    ) == (
                        {id_values_str}
                    )
                ), 'null')
            """

        query = f"""
            INSERT OR REPLACE INTO {info.table_prefix}tags (
                {id_columns_str}, value
            ) VALUES (
                {id_values_str}, {value_str}
            )
        """

        with self.get_db() as db:
            try:
                db.execute(query, params)
            except sqlite3.IntegrityError as e:
                foreign_key_error = "foreign key constraint failed" in str(e).lower()
                if not foreign_key_error:  # pragma: no cover
                    raise
                raise info.not_found_exc(*resource_id) from None

    @wrap_exceptions(StorageError)
    def delete_tag(self, resource_id: ResourceId, key: str) -> None:
        info = SCHEMA_INFO[len(resource_id)]

        columns = info.id_columns + ('key',)
        query = f"""
            DELETE FROM {info.table_prefix}tags
            WHERE (
                {', '.join(columns)}
            ) = (
                {', '.join(('?' for _ in columns))}
            )
        """
        params = resource_id + (key,)

        with self.get_db() as db:
            cursor = db.execute(query, params)
        rowcount_exactly_one(cursor, lambda: TagNotFoundError(resource_id, key))


def make_get_feeds_query(
    filter_options: FeedFilterOptions, sort: FeedSortOrder
) -> tuple[Query, dict[str, Any]]:
    query = (
        Query()
        .SELECT(
            'url',
            'updated',
            'title',
            'link',
            'author',
            'subtitle',
            'version',
            'user_title',
            'added',
            'last_updated',
            'last_exception',
            'updates_enabled',
        )
        .FROM("feeds")
    )

    context = apply_feed_filter_options(query, filter_options)

    # NOTE: when changing, ensure none of the values can be null
    # to prevent https://github.com/lemon24/reader/issues/203

    # sort by url at the end to make sure the order is deterministic
    if sort == 'title':
        query.SELECT(("kinda_title", "lower(coalesce(user_title, title, ''))"))
        query.scrolling_window_order_by("kinda_title", "url")
    elif sort == 'added':
        query.SELECT("added")
        query.scrolling_window_order_by("added", "url", desc=True)
    else:
        assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

    return query, context


def feed_factory(t: tuple[Any, ...]) -> Feed:
    return Feed._make(
        t[:10]
        + (
            ExceptionInfo(**json.loads(t[10])) if t[10] else None,
            t[11] == 1,
        )
    )


def apply_feed_filter_options(
    query: Query,
    filter_options: FeedFilterOptions,
) -> dict[str, Any]:
    url, tags, broken, updates_enabled, new = filter_options

    context: dict[str, object] = {}

    if url:
        query.WHERE("url = :url")
        context.update(url=url)

    context.update(apply_feed_tags_filter_options(query, tags, 'feeds.url'))

    if broken is not None:
        query.WHERE(f"last_exception IS {'NOT' if broken else ''} NULL")
    if updates_enabled is not None:
        query.WHERE(f"{'' if updates_enabled else 'NOT'} updates_enabled")
    if new is not None:
        query.WHERE(f"last_updated is {'' if new else 'NOT'} NULL")

    return context


def make_get_entries_query(
    filter_options: EntryFilterOptions,
    sort: EntrySortOrder,
) -> tuple[Query, dict[str, Any]]:
    query = (
        Query()
        .SELECT(
            *"""
            entries.feed
            feeds.updated
            feeds.title
            feeds.link
            feeds.author
            feeds.subtitle
            feeds.version
            feeds.user_title
            feeds.added
            feeds.last_updated
            feeds.last_exception
            feeds.updates_enabled
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
            entries.read_modified
            entries.important
            entries.important_modified
            entries.first_updated
            entries.added_by
            entries.last_updated
            entries.original_feed
            """.split()
        )
        .FROM("entries")
        .JOIN("feeds ON feeds.url = entries.feed")
    )

    filter_context = apply_entry_filter_options(query, filter_options)

    if sort == 'recent':
        apply_recent(query)

    elif sort == 'random':
        apply_random(query)

    else:
        assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

    log.debug("_get_entries query\n%s\n", query)

    return query, filter_context


def entry_factory(t: tuple[Any, ...]) -> Entry:
    feed = feed_factory(t[0:12])
    entry = t[12:19] + (
        tuple(Content(**d) for d in json.loads(t[19])) if t[19] else (),
        tuple(Enclosure(**d) for d in json.loads(t[20])) if t[20] else (),
        t[21] == 1,
        t[22],
        t[23] == 1 if t[23] is not None else None,
        t[24],
        t[25],
        t[26],
        t[27],
        t[28] or feed.url,
        feed,
    )
    return Entry._make(entry)


TRISTATE_FILTER_TO_SQL = dict(
    istrue="({expr} IS NOT NULL AND {expr})",
    isfalse="({expr} IS NOT NULL AND NOT {expr})",
    notset="{expr} IS NULL",
    nottrue="({expr} IS NULL OR NOT {expr})",
    notfalse="({expr} IS NULL OR {expr})",
    isset="{expr} IS NOT NULL",
)


def apply_entry_filter_options(
    query: Query, filter_options: EntryFilterOptions, keyword: str = 'WHERE'
) -> dict[str, Any]:
    add = getattr(query, keyword)
    feed_url, entry_id, read, important, has_enclosures, feed_tags = filter_options

    context = {}

    if feed_url:
        add("entries.feed = :feed_url")
        context['feed_url'] = feed_url
        if entry_id:
            add("entries.id = :entry_id")
            context['entry_id'] = entry_id

    if read is not None:
        add(f"{'' if read else 'NOT'} entries.read")

    if important != 'any':
        add(TRISTATE_FILTER_TO_SQL[important].format(expr='entries.important'))

    if has_enclosures is not None:
        add(
            f"""
            {'NOT' if has_enclosures else ''}
                (json_array_length(entries.enclosures) IS NULL
                    OR json_array_length(entries.enclosures) = 0)
            """
        )

    context.update(
        apply_feed_tags_filter_options(
            query, feed_tags, 'entries.feed', keyword=keyword
        )
    )

    return context


def apply_feed_tags_filter_options(
    query: Query,
    tags: TagFilter,
    url_column: str,
    keyword: str = 'WHERE',
) -> dict[str, Any]:
    add = getattr(query, keyword)

    context = {}

    add_tags_cte = False
    add_tags_count_cte = False

    next_tag_id = 0

    for subtags in tags:
        tag_query = BaseQuery({'(': [], ')': ['']}, {'(': 'OR'})
        tag_add = partial(tag_query.add, '(')

        for maybe_tag in subtags:
            if isinstance(maybe_tag, bool):
                tag_add(f"{'NOT' if not maybe_tag else ''} (SELECT * FROM tags_count)")
                add_tags_count_cte = True
                continue

            is_negation, tag = maybe_tag
            tag_name = f'__tag_{next_tag_id}'
            next_tag_id += 1
            context[tag_name] = tag
            tag_add(f":{tag_name} {'NOT' if is_negation else ''} IN tags")
            add_tags_cte = True

        add(str(tag_query))

    if add_tags_cte:
        query.WITH(("tags", f"SELECT key FROM feed_tags WHERE feed = {url_column}"))

    if add_tags_count_cte:
        query.WITH(
            (
                "tags_count",
                f"SELECT count(key) FROM feed_tags WHERE feed = {url_column}",
            )
        )

    return context


def make_recent_last_select(id_prefix: str = 'entries.') -> Sequence[Any]:
    return [
        'recent_sort',
        ('kinda_published', 'coalesce(published, updated, first_updated)'),
        f'{id_prefix}feed',
        'last_updated',
        ('negative_feed_order', '- feed_order'),
        f'{id_prefix}id',
    ]


def apply_recent(
    query: Query, keyword: str = 'WHERE', id_prefix: str = 'entries.'
) -> None:
    """Change query to sort entries by "recent"."""

    # WARNING: Always keep the entries_by_recent index in sync
    # with the ORDER BY of the CTE below.

    query.WITH(
        (
            'ids',
            """
            SELECT
                feed,
                id,
                last_updated,
                recent_sort,
                coalesce(published, updated, first_updated) as kinda_published,
                - feed_order as negative_feed_order
            FROM entries
            ORDER BY
                recent_sort DESC,
                kinda_published DESC,
                feed DESC,
                last_updated DESC,
                negative_feed_order DESC,
                id DESC
            """,
        ),
    )
    query.JOIN(f"ids ON (ids.id, ids.feed) = ({id_prefix}id, {id_prefix}feed)")

    query.SELECT(
        'ids.recent_sort',
        'ids.kinda_published',
        'ids.feed',
        'ids.last_updated',
        'ids.negative_feed_order',
        'ids.id',
    )

    # NOTE: when changing, ensure none of the values can be null
    # to prevent https://github.com/lemon24/reader/issues/203
    query.scrolling_window_order_by(
        'ids.recent_sort',
        'ids.kinda_published',
        'ids.feed',
        'ids.last_updated',
        'ids.negative_feed_order',
        'ids.id',
        desc=True,
        keyword=keyword,
    )


def apply_random(query: Query) -> None:
    # TODO: "order by random()" always goes through the full result set,
    # which is inefficient; details:
    # https://github.com/lemon24/reader/issues/105#issue-409493128
    #
    # This is a separate function in the hope that search
    # can benefit from future optimizations.
    #
    query.ORDER_BY("random()")


def make_entry_counts_query(
    now: datetime,
    average_periods: tuple[float, ...],
    entries_query: Query,
) -> tuple[Query, dict[str, Any]]:
    query = (
        Query()
        .WITH(('entries_filtered', str(entries_query)))
        .SELECT(
            'count(*)',
            'coalesce(sum(read == 1), 0)',
            'coalesce(sum(important == 1), 0)',
            """
            coalesce(
                sum(
                    NOT (
                        json_array_length(entries.enclosures) IS NULL OR json_array_length(entries.enclosures) = 0
                    )
                ), 0
            )
            """,
        )
        .FROM("entries_filtered")
        .JOIN("entries USING (id, feed)")
    )

    # one CTE / period + HAVING in the CTE is a tiny bit faster than
    # one CTE + WHERE in the SELECT

    context: dict[str, Any] = dict(now=now)

    for period_i, period_days in enumerate(average_periods):
        # TODO: when we get first_updated, use it instead of first_updated_epoch

        days_param = f'kfu_{period_i}_days'
        context[days_param] = float(period_days)

        start_param = f'kfu_{period_i}_start'
        context[start_param] = now - timedelta(days=period_days)

        kfu_query = (
            Query()
            .SELECT('coalesce(published, updated, first_updated_epoch) AS kfu')
            .FROM('entries_filtered')
            .JOIN("entries USING (id, feed)")
            .GROUP_BY('published, updated, first_updated_epoch, feed')
            .HAVING(f"kfu BETWEEN :{start_param} AND :now")
        )

        query.WITH((f'kfu_{period_i}', str(kfu_query)))
        query.SELECT(f"(SELECT count(*) / :{days_param} FROM kfu_{period_i})")

    return query, context


def entry_update_intent_to_dict(intent: EntryUpdateIntent) -> Mapping[str, Any]:
    context = intent._asdict()
    entry = context.pop('entry')
    context.update(
        entry._asdict(),
        content=(
            json.dumps([t._asdict() for t in entry.content]) if entry.content else None
        ),
        enclosures=(
            json.dumps([t._asdict() for t in entry.enclosures])
            if entry.enclosures
            else None
        ),
        data_hash=entry.hash,
        data_hash_changed=context.pop('hash_changed'),
    )
    return context
