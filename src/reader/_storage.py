import json
import logging
import sqlite3
from datetime import datetime
from datetime import timedelta
from functools import partial
from typing import Any
from typing import cast
from typing import Dict
from typing import Iterable
from typing import Mapping
from typing import NamedTuple
from typing import Optional
from typing import overload
from typing import Sequence
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union

from ._sql_utils import BaseQuery
from ._sql_utils import paginated_query
from ._sql_utils import Query
from ._sqlite_utils import DBError
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
            read INTEGER NOT NULL DEFAULT 0,
            read_modified TIMESTAMP,
            important INTEGER NOT NULL DEFAULT 0,
            important_modified TIMESTAMP,
            added_by TEXT NOT NULL,
            last_updated TIMESTAMP NOT NULL,
            first_updated TIMESTAMP NOT NULL,
            first_updated_epoch TIMESTAMP NOT NULL,
            feed_order INTEGER NOT NULL,

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
    id_columns: Tuple[str, ...]
    not_found_exc: Type[ReaderError]


SCHEMA_INFO = {
    0: SchemaInfo('global_', (), ReaderError),
    1: SchemaInfo('feed_', ('feed',), FeedNotFoundError),
    2: SchemaInfo('entry_', ('feed', 'id'), EntryNotFoundError),
}


def create_indexes(db: sqlite3.Connection) -> None:
    # Speed up get_entries() queries that use apply_recent().
    db.execute(
        """
        CREATE INDEX entries_by_kinda_first_updated ON entries(
            first_updated_epoch,
            coalesce(published, updated, first_updated),
            feed,
            last_updated,
            - feed_order,
            id
        );
        """
    )
    db.execute(
        """
        CREATE INDEX entries_by_kinda_published ON entries (
            coalesce(published, updated, first_updated),
            coalesce(published, updated, first_updated),
            feed,
            last_updated,
            - feed_order,
            id
        );
        """
    )
    # Speed up get_entry_counts(feed=...).
    db.execute("CREATE INDEX entries_by_feed ON entries (feed);")


def update_from_29_to_30(db: sqlite3.Connection) -> None:  # pragma: no cover
    # for https://github.com/lemon24/reader/issues/251
    db.execute("CREATE INDEX entries_by_feed ON entries (feed);")


def recreate_search_triggers(db: sqlite3.Connection) -> None:  # pragma: no cover
    from ._search import Search

    search = Search(db)
    if search.is_enabled():
        search._drop_triggers()
        search._create_triggers()


def update_from_31_to_32(db: sqlite3.Connection) -> None:  # pragma: no cover
    # for https://github.com/lemon24/reader/issues/254
    db.execute("ALTER TABLE entries ADD COLUMN read_modified TIMESTAMP;")
    db.execute("ALTER TABLE entries ADD COLUMN important_modified TIMESTAMP;")


def update_from_32_to_33(db: sqlite3.Connection) -> None:  # pragma: no cover
    # https://github.com/lemon24/reader/issues/223
    db.execute("ALTER TABLE feeds ADD COLUMN subtitle TEXT;")
    db.execute("ALTER TABLE feeds ADD COLUMN version TEXT;")
    # force all feeds to update regardless of their caching headers
    db.execute("UPDATE feeds SET stale = 1;")


def update_from_33_to_34(db: sqlite3.Connection) -> None:  # pragma: no cover
    # for https://github.com/lemon24/reader/issues/239

    # Assumes foreign key checks have already been disabled.
    # https://sqlite.org/lang_altertable.html#otheralter

    # This migration takes care of:
    #
    # * first_updated being added not null
    # * updated becoming null
    # * re-creating the entries_by_kinda_* indexes to use first_updated
    # * added_by being added not null

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
            original_feed,
            data_hash,
            data_hash_changed,
            read,
            read_modified,
            important,
            important_modified,
            'feed',
            last_updated,
            first_updated_epoch,
            first_updated_epoch,
            feed_order
        FROM entries;
        """
    )
    # IMPORTANT: this drops ALL indexes and triggers ON entries
    db.execute("DROP TABLE entries;")
    db.execute("ALTER TABLE new_entries RENAME TO entries;")

    create_indexes(db)
    recreate_search_triggers(db)


def update_from_34_to_35(db: sqlite3.Connection) -> None:  # pragma: no cover
    # for https://github.com/lemon24/reader/issues/266
    db.execute(
        """
        INSERT OR REPLACE INTO feed_metadata (feed, key, value)
        SELECT feed, tag, coalesce((
            SELECT value FROM feed_metadata AS fm
            WHERE (fm.feed, fm.key) == (feed, tag)
        ), 'null')
        FROM feed_tags;
        """
    )
    db.execute("DROP TABLE feed_tags;")
    db.execute("ALTER TABLE feed_metadata RENAME TO feed_tags;")


def update_from_35_to_36(db: sqlite3.Connection) -> None:  # pragma: no cover
    # for https://github.com/lemon24/reader/issues/272
    create_global_tags(db)
    create_entry_tags(db)


MINIMUM_SQLITE_VERSION = (3, 15)
REQUIRED_SQLITE_COMPILE_OPTIONS = ["ENABLE_JSON1"]


def setup_db(db: sqlite3.Connection, wal_enabled: Optional[bool]) -> None:
    return setup_sqlite_db(
        db,
        create=create_db,
        version=36,
        migrations={
            # 1-9 removed before 0.1 (last in e4769d8ba77c61ec1fe2fbe99839e1826c17ace7)
            # 10-16 removed before 1.0 (last in 618f158ebc0034eefb724a55a84937d21c93c1a7)
            # 17-28 removed before 2.0 (last in be9c89581ea491d0c9cc95c9d39f073168a2fd02)
            29: update_from_29_to_30,
            30: recreate_search_triggers,
            31: update_from_31_to_32,
            32: update_from_32_to_33,
            33: update_from_33_to_34,
            34: update_from_34_to_35,
            35: update_from_35_to_36,
        },
        id=APPLICATION_ID,
        # Row value support was added in 3.15.
        # TODO: Remove the Search.update() check once this gets bumped to >=3.18.
        minimum_sqlite_version=MINIMUM_SQLITE_VERSION,
        # We use the JSON1 extension for entries.content.
        required_sqlite_compile_options=REQUIRED_SQLITE_COMPILE_OPTIONS,
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


class Storage:

    # recent_threshold, chunk_size, and entry_counts_average_periods
    # are not part of the Storage interface,
    # but are part of the private API of this implementation.
    recent_threshold = timedelta(7)
    chunk_size = 2 ** 8
    # 1, 3, 12 months rounded down to days,
    # assuming an average of 30.436875 days/month
    entry_counts_average_periods = (30, 91, 365)

    @wrap_exceptions(StorageError)
    def __init__(
        self,
        path: str,
        timeout: Optional[float] = None,
        wal_enabled: Optional[bool] = True,
        factory: Optional[Type[sqlite3.Connection]] = None,
    ):
        kwargs: Dict[str, Any] = {}
        if timeout is not None:
            kwargs['timeout'] = timeout
        if factory:  # pragma: no cover
            kwargs['factory'] = factory

        with wrap_exceptions(StorageError, "error while opening database"):
            db = self.connect(path, detect_types=sqlite3.PARSE_DECLTYPES, **kwargs)

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
                    message += "; you may have skipped some required migrations, see https://reader.readthedocs.io/en/latest/changelog.html#removed-migrations-2-0"
                raise StorageError(message=message) from None

        self.db: sqlite3.Connection = db
        self.path = path
        self.timeout = timeout

    # TODO: these are not part of the Storage API
    connect = staticmethod(sqlite3.connect)
    setup_db = staticmethod(setup_db)

    @wrap_exceptions(StorageError)
    def close(self) -> None:
        # If "PRAGMA optimize" on every close becomes too expensive, we can
        # add an option to disable it, or call db.interrupt() after some time.
        # TODO: Once SQLite 3.32 becomes widespread, use "PRAGMA analysis_limit"
        # for the same purpose. Details:
        # https://github.com/lemon24/reader/issues/143#issuecomment-663433197
        try:
            self.db.execute("PRAGMA optimize;")
        except sqlite3.ProgrammingError as e:
            # Calling close() a second time is a noop.
            if "cannot operate on a closed database" in str(e).lower():
                return
            raise

        self.db.close()

    @wrap_exceptions(StorageError)
    def add_feed(self, url: str, added: datetime) -> None:
        with self.db:
            try:
                self.db.execute(
                    "INSERT INTO feeds (url, added) VALUES (:url, :added);",
                    dict(url=url, added=added),
                )
            except sqlite3.IntegrityError as e:
                if "unique constraint failed" not in str(e).lower():  # pragma: no cover
                    raise
                raise FeedExistsError(url) from None

    @wrap_exceptions(StorageError)
    def delete_feed(self, url: str) -> None:
        with self.db:
            cursor = self.db.execute(
                "DELETE FROM feeds WHERE url = :url;", dict(url=url)
            )
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def change_feed_url(self, old: str, new: str) -> None:
        with self.db:
            try:
                cursor = self.db.execute(
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
            self.db.execute(
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

            self.db.execute(
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
        limit: Optional[int] = None,
        starting_after: Optional[str] = None,
    ) -> Iterable[Feed]:
        rv = join_paginated_iter(
            partial(self.get_feeds_page, filter_options, sort),  # type: ignore[arg-type]
            self.chunk_size,
            self.get_feed_last(sort, starting_after) if starting_after else None,
            limit or 0,
        )
        yield from rv

    @wrap_exceptions(StorageError)
    def get_feed_last(self, sort: str, url: str) -> Tuple[Any, ...]:
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
            self.db.execute(str(query), dict(url=url)), lambda: FeedNotFoundError(url)
        )

    @wrap_exceptions_iter(StorageError)
    def get_feeds_page(
        self,
        filter_options: FeedFilterOptions = FeedFilterOptions(),  # noqa: B008
        sort: FeedSortOrder = 'title',
        chunk_size: Optional[int] = None,
        last: Optional[_T] = None,
    ) -> Iterable[Tuple[Feed, Optional[_T]]]:
        query, context = make_get_feeds_query(filter_options, sort)
        yield from paginated_query(
            self.db, query, context, chunk_size, last, feed_factory
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

        row = exactly_one(self.db.execute(str(query), context))

        return FeedCounts(*row)

    @wrap_exceptions_iter(StorageError)
    def get_feeds_for_update(
        self,
        filter_options: FeedFilterOptions = FeedFilterOptions(),  # noqa: B008
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
                    ('last_exception', 'last_exception IS NOT NULL'),
                    'data_hash',
                )
                .FROM("feeds")
            )

            # TODO: stale and last_exception should be bool, not int

            context = apply_feed_filter_options(query, filter_options)

            query.scrolling_window_order_by("url")

            yield from paginated_query(
                self.db, query, context, chunk_size, last, FeedForUpdate._make
            )

        yield from join_paginated_iter(inner, self.chunk_size)

    def _get_entries_for_update(
        self, entries: Iterable[Tuple[str, str]]
    ) -> Iterable[Optional[EntryForUpdate]]:
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

        with self.db:
            # We use an explicit transaction for speed,
            # otherwise we get an implicit one for each query).
            self.db.execute('BEGIN;')

            for feed_url, id in entries:  # noqa: B007
                context = dict(feed_url=feed_url, id=id)
                row = self.db.execute(
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
        self, entries: Iterable[Tuple[str, str]]
    ) -> Iterable[Optional[EntryForUpdate]]:
        # It's acceptable for this method to not be atomic. TODO: Why?

        iterables = chunks(self.chunk_size, entries) if self.chunk_size else (entries,)

        for iterable in iterables:
            rv = self._get_entries_for_update(iterable)
            if self.chunk_size:
                rv = list(rv)
            yield from rv

    @wrap_exceptions(StorageError)
    def set_feed_user_title(self, url: str, title: Optional[str]) -> None:
        with self.db:
            cursor = self.db.execute(
                "UPDATE feeds SET user_title = :title WHERE url = :url;",
                dict(url=url, title=title),
            )
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def set_feed_updates_enabled(self, url: str, enabled: bool) -> None:
        with self.db:
            cursor = self.db.execute(
                "UPDATE feeds SET updates_enabled = :updates_enabled WHERE url = :url;",
                dict(url=url, updates_enabled=enabled),
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def mark_as_stale(self, url: str) -> None:
        with self.db:
            cursor = self.db.execute(
                "UPDATE feeds SET stale = 1 WHERE url = :url;", dict(url=url)
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def mark_as_read(
        self, feed_url: str, entry_id: str, read: bool, modified: Optional[datetime]
    ) -> None:
        with self.db:
            cursor = self.db.execute(
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
        important: bool,
        modified: Optional[datetime],
    ) -> None:
        with self.db:
            cursor = self.db.execute(
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

        with self.db:
            cursor = self.db.execute(
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
        with self.db:
            cursor = self.db.execute(
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
        with self.db:
            cursor = self.db.execute(
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
                coalesce((
                    SELECT important
                    FROM entries
                    WHERE id = :id AND feed = :feed_url
                ), 0),
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
                NULL, -- original_feed
                :data_hash,
                :data_hash_changed,
                :added_by
            );
        """

        with self.db:
            try:
                # we could use executemany(), but it's not noticeably faster
                for intent in intents:
                    self.db.execute(query, entry_update_intent_to_dict(intent))

            except sqlite3.IntegrityError as e:
                e_msg = str(e).lower()
                feed_url, entry_id = intent.entry.object_id

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
        self, entries: Iterable[Tuple[str, str]], *, added_by: Optional[str] = None
    ) -> None:
        # This must be atomic (unlike add_or_update_entries()); hence, no paging.
        # We'll deal with locking issues only if they start appearing
        # (hopefully, there are both fewer entries to be deleted and
        # this takes less time per entry).

        delete_query = "DELETE FROM entries WHERE feed = :feed AND id = :id"
        added_by_query = "SELECT added_by FROM entries WHERE feed = :feed AND id = :id"

        with self.db:
            cursor = self.db.cursor()

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
                    cursor, lambda: EntryNotFoundError(feed_url, entry_id)
                )

    def get_entries(
        self,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        sort: EntrySortOrder = 'recent',
        limit: Optional[int] = None,
        starting_after: Optional[Tuple[str, str]] = None,
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
        self, now: datetime, sort: str, entry: Tuple[str, str]
    ) -> Tuple[Any, ...]:
        # TODO: make this method private?

        feed_url, entry_id = entry

        query = Query().FROM("entries").WHERE("feed = :feed AND id = :id")

        assert sort != 'random'

        # TODO: kinda sorta duplicates the scrolling_window_order_by call
        if sort == 'recent':
            query.SELECT(*make_recent_last_select())
        else:
            assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

        context = dict(
            feed=feed_url,
            id=entry_id,
            # TODO: duplicated from get_entries_page()
            recent_threshold=now - self.recent_threshold,
        )

        return zero_or_one(
            self.db.execute(str(query), context),
            lambda: EntryNotFoundError(feed_url, entry_id),
        )

    @wrap_exceptions_iter(StorageError)
    def get_entries_page(
        self,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        sort: EntrySortOrder = 'recent',
        chunk_size: Optional[int] = None,
        last: Optional[_T] = None,
    ) -> Iterable[Tuple[Entry, Optional[_T]]]:
        query, context = make_get_entries_query(filter_options, sort)
        context.update(recent_threshold=now - self.recent_threshold)
        yield from paginated_query(
            self.db, query, context, chunk_size, last, entry_factory
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

        row = exactly_one(self.db.execute(str(query), context))

        return EntryCounts(*row[:4], row[4:7])  # type: ignore[call-arg]

    def get_tags(
        self,
        object_id: AnyResourceId,
        key: Optional[str] = None,
    ) -> Iterable[Tuple[str, JSONType]]:
        yield from join_paginated_iter(
            partial(self.get_tags_page, object_id, key),
            self.chunk_size,
        )

    @wrap_exceptions_iter(StorageError)
    def get_tags_page(
        self,
        object_id: AnyResourceId,
        key: Optional[str] = None,
        chunk_size: Optional[int] = None,
        last: Optional[_T] = None,
    ) -> Iterable[Tuple[Tuple[str, JSONType], Optional[_T]]]:
        query = Query().SELECT("key")
        context: Dict[str, Any] = dict()

        if object_id is not None:
            info = SCHEMA_INFO[len(object_id)]
            query.FROM(f"{info.table_prefix}tags")

            if not any(p is None for p in object_id):
                query.SELECT("value")
                for column in info.id_columns:
                    query.WHERE(f"{column} = :{column}")
                context.update(zip(info.id_columns, object_id))
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

        def row_factory(t: Tuple[Any, ...]) -> Tuple[str, JSONType]:
            key, value, *_ = t
            return key, json.loads(value)

        yield from paginated_query(
            self.db, query, context, chunk_size, last, row_factory
        )

    @overload
    def set_tag(self, object_id: ResourceId, key: str) -> None:  # pragma: no cover
        ...

    @overload
    def set_tag(
        self, object_id: ResourceId, key: str, value: JSONType
    ) -> None:  # pragma: no cover
        ...

    @wrap_exceptions(StorageError)
    def set_tag(
        self,
        object_id: ResourceId,
        key: str,
        value: Union[MissingType, JSONType] = MISSING,
    ) -> None:
        info = SCHEMA_INFO[len(object_id)]

        params = dict(zip(info.id_columns, object_id), key=key)

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

        with self.db:
            try:
                self.db.execute(query, params)
            except sqlite3.IntegrityError as e:
                foreign_key_error = "foreign key constraint failed" in str(e).lower()
                if not foreign_key_error:  # pragma: no cover
                    raise
                raise info.not_found_exc(*object_id) from None

    @wrap_exceptions(StorageError)
    def delete_tag(self, object_id: ResourceId, key: str) -> None:
        info = SCHEMA_INFO[len(object_id)]

        columns = info.id_columns + ('key',)
        query = f"""
            DELETE FROM {info.table_prefix}tags
            WHERE (
                {', '.join(columns)}
            ) = (
                {', '.join(('?' for _ in columns))}
            )
        """
        params = object_id + (key,)

        with self.db:
            cursor = self.db.execute(query, params)
        rowcount_exactly_one(cursor, lambda: TagNotFoundError(key, cast(str, None)))


def make_get_feeds_query(
    filter_options: FeedFilterOptions, sort: FeedSortOrder
) -> Tuple[Query, Dict[str, Any]]:
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


def feed_factory(t: Tuple[Any, ...]) -> Feed:
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
) -> Dict[str, Any]:
    url, tags, broken, updates_enabled, new = filter_options

    context: Dict[str, object] = {}

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
) -> Tuple[Query, Dict[str, Any]]:
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


def entry_factory(t: Tuple[Any, ...]) -> Entry:
    feed = feed_factory(t[0:12])
    entry = t[12:19] + (
        tuple(Content(**d) for d in json.loads(t[19])) if t[19] else (),
        tuple(Enclosure(**d) for d in json.loads(t[20])) if t[20] else (),
        t[21] == 1,
        t[22],
        t[23] == 1,
        t[24],
        t[25],
        t[26],
        t[27],
        t[28] or feed.url,
        feed,
    )
    return Entry._make(entry)


def apply_entry_filter_options(
    query: Query, filter_options: EntryFilterOptions, keyword: str = 'WHERE'
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
        (
            'kinda_first_updated',
            """
            coalesce (
                CASE
                WHEN
                    coalesce(entries.published, entries.updated, entries.first_updated)
                        >= :recent_threshold
                    THEN entries.first_updated_epoch
                END,
                entries.published, entries.updated, entries.first_updated
            )
            """,
        ),
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

    # Version of apply_recent() that takes advantage of indexes, implemented in
    # <https://github.com/lemon24/reader/issues/134#issuecomment-722454963>.
    # An older version that does not can be found in reader 1.9.
    #
    # WARNING: Always keep the entries_by_kinda_* indexes in sync with the ORDER BY of the by_kinda_* CTEs below.

    def make_by_kinda_cte(recent: bool) -> str:
        if recent:
            kinda_first_updated = 'first_updated_epoch'
            sign = '>='
        else:
            kinda_first_updated = 'coalesce(published, updated, first_updated)'
            sign = '<'

        return f"""
            SELECT
                feed,
                id,
                last_updated,
                {kinda_first_updated} as kinda_first_updated,
                coalesce(published, updated, first_updated) as kinda_published,
                - feed_order as negative_feed_order
            FROM entries
            WHERE kinda_published {sign} :recent_threshold
            ORDER BY
                kinda_first_updated DESC,
                kinda_published DESC,
                feed DESC,
                last_updated DESC,
                negative_feed_order DESC,
                id DESC
        """

    query.WITH(
        ('by_kinda_first_updated', make_by_kinda_cte(recent=True)),
        ('by_kinda_published', make_by_kinda_cte(recent=False)),
        (
            'ids',
            """
            SELECT * FROM by_kinda_first_updated
            UNION ALL
            SELECT * FROM by_kinda_published
            """,
        ),
    )
    query.JOIN(f"ids ON (ids.id, ids.feed) = ({id_prefix}id, {id_prefix}feed)")

    query.SELECT(
        "ids.last_updated",
        "kinda_first_updated",
        "kinda_published",
        "negative_feed_order",
    )

    # NOTE: when changing, ensure none of the values can be null
    # to prevent https://github.com/lemon24/reader/issues/203
    query.scrolling_window_order_by(
        'kinda_first_updated',
        'kinda_published',
        f'{id_prefix}feed',
        'ids.last_updated',
        'negative_feed_order',
        f'{id_prefix}id',
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
    average_periods: Tuple[float, ...],
    entries_query: Query,
) -> Tuple[Query, Dict[str, Any]]:
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

    context: Dict[str, Any] = dict(now=now)

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
