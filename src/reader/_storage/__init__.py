from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import partial
from typing import Any
from typing import NamedTuple
from typing import overload
from typing import TypeVar

from . import _queries
from .._types import EntryFilter
from .._types import EntryForUpdate
from .._types import EntryUpdateIntent
from .._types import FeedFilter
from .._types import FeedForUpdate
from .._types import FeedUpdateIntent
from .._types import SearchType
from .._types import TagFilter
from .._utils import chunks
from .._utils import exactly_one
from .._utils import zero_or_one
from ..exceptions import EntryError
from ..exceptions import EntryExistsError
from ..exceptions import EntryNotFoundError
from ..exceptions import FeedExistsError
from ..exceptions import FeedNotFoundError
from ..exceptions import ReaderError
from ..exceptions import StorageError
from ..exceptions import TagNotFoundError
from ..types import AnyResourceId
from ..types import Content
from ..types import Enclosure
from ..types import Entry
from ..types import EntryCounts
from ..types import EntrySort
from ..types import ExceptionInfo
from ..types import Feed
from ..types import FeedCounts
from ..types import FeedSort
from ..types import JSONType
from ..types import MISSING
from ..types import MissingType
from ..types import ResourceId
from ._queries import adapt_datetime
from ._queries import convert_timestamp
from ._sql_utils import BaseQuery
from ._sql_utils import paginated_query
from ._sql_utils import Query
from ._sqlite_utils import DBError
from ._sqlite_utils import LocalConnectionFactory
from ._sqlite_utils import rowcount_exactly_one
from ._sqlite_utils import setup_db as setup_sqlite_db
from ._sqlite_utils import wrap_exceptions
from ._sqlite_utils import wrap_exceptions_iter

APPLICATION_ID = int(''.join(f'{ord(c):x}' for c in 'read'), 16)


log = logging.getLogger('reader')


_T = TypeVar('_T')


class SchemaInfo(NamedTuple):
    table_prefix: str
    id_columns: tuple[str, ...]
    not_found_exc: type[ReaderError]


SCHEMA_INFO = {
    0: SchemaInfo('global_', (), ReaderError),
    1: SchemaInfo('feed_', ('feed',), FeedNotFoundError),
    2: SchemaInfo('entry_', ('feed', 'id'), EntryNotFoundError),
}


# Row value support was added in 3.15.
# TODO: Remove the Search.update() check once this gets bumped to >=3.18.
MINIMUM_SQLITE_VERSION = (3, 15)
# We use the JSON1 extension for entries.content.
REQUIRED_SQLITE_FUNCTIONS = ['json_array_length']


def setup_db(db: sqlite3.Connection, wal_enabled: bool | None) -> None:
    from . import _schema

    return setup_sqlite_db(
        db,
        create=_schema.create_all,
        version=_schema.VERSION,
        migrations=_schema.MIGRATIONS,
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
            self.factory = LocalConnectionFactory(path, **kwargs)
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

    def make_search(self) -> SearchType:
        from ._search import Search

        return Search(self)

    @wrap_exceptions(StorageError)
    def add_feed(self, url: str, added: datetime) -> None:
        with self.get_db() as db:
            try:
                db.execute(
                    "INSERT INTO feeds (url, added) VALUES (:url, :added);",
                    dict(url=url, added=adapt_datetime(added)),
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

    @wrap_exceptions_iter(StorageError)
    def get_feeds(
        self,
        filter: FeedFilter = FeedFilter(),  # noqa: B008
        sort: FeedSort = 'title',
        limit: int | None = None,
        starting_after: str | None = None,
    ) -> Iterable[Feed]:
        return paginated_query(
            self.get_db(),
            partial(_queries.get_feeds, filter, sort),
            self.chunk_size,
            limit or 0,
            self.get_feed_last(sort, starting_after) if starting_after else None,
            _queries.feed_factory,
        )

    def get_feed_last(self, sort: FeedSort, url: str) -> tuple[Any, ...]:
        query = (
            Query()
            .SELECT(*_queries.FEED_SORT_KEYS[sort])
            .FROM("feeds")
            .WHERE("url = :url")
        )
        return zero_or_one(
            self.get_db().execute(str(query), dict(url=url)),
            lambda: FeedNotFoundError(url),
        )

    @wrap_exceptions(StorageError)
    def get_feed_counts(
        self,
        filter: FeedFilter = FeedFilter(),  # noqa: B008
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

        context = _queries.feed_filter(query, filter)

        row = exactly_one(self.get_db().execute(str(query), context))

        return FeedCounts(*row)

    @wrap_exceptions_iter(StorageError)
    def get_feeds_for_update(
        self,
        filter: FeedFilter = FeedFilter(),  # noqa: B008
    ) -> Iterable[FeedForUpdate]:
        def row_factory(row: tuple[Any, ...]) -> FeedForUpdate:
            (
                url,
                updated,
                http_etag,
                http_last_modified,
                stale,
                last_updated,
                last_exception,
                data_hash,
            ) = row
            return FeedForUpdate(
                url,
                convert_timestamp(updated) if updated else None,
                http_etag,
                http_last_modified,
                stale == 1,
                convert_timestamp(last_updated) if last_updated else None,
                last_exception == 1,
                data_hash,
            )

        def make_query() -> tuple[Query, dict[str, Any]]:
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
                .scrolling_window_order_by("url")
            )
            context = _queries.feed_filter(query, filter)
            return query, context

        return paginated_query(
            self.get_db(),
            make_query,
            self.chunk_size,
            row_factory=row_factory,
        )

    @wrap_exceptions_iter(StorageError)
    def get_entries_for_update(
        self, entries: Iterable[tuple[str, str]]
    ) -> Iterable[EntryForUpdate | None]:
        for iterable in chunks(self.chunk_size, entries):
            yield from self._get_entries_for_update_page(iterable)

    def _get_entries_for_update_page(
        self, entries: Iterable[tuple[str, str]]
    ) -> Iterable[EntryForUpdate | None]:
        # Fetching everything in a single query is not much faster.
        # Also, the maximum number of SQL variables can be as low as 999.
        # See https://github.com/lemon24/reader/issues/109 for details.
        # See e39b0134cb3a2fe2bb346d42355a764181926a82 for a single query version.

        def row_factory(_: sqlite3.Cursor, row: sqlite3.Row) -> EntryForUpdate:
            updated, published, data_hash, data_hash_changed = row
            return EntryForUpdate(
                convert_timestamp(updated) if updated else None,
                convert_timestamp(published) if published else None,
                data_hash,
                data_hash_changed,
            )

        query = """
            SELECT
                updated,
                published,
                data_hash,
                data_hash_changed
            FROM entries
            WHERE feed = ?
                AND id = ?;
        """

        with self.get_db() as db:
            cursor = db.cursor()
            cursor.row_factory = row_factory

            # Use an explicit transaction for speed.
            cursor.execute('BEGIN;')

            return [cursor.execute(query, entry).fetchone() for entry in entries]

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
    def set_feed_stale(self, url: str, stale: bool) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                "UPDATE feeds SET stale = :stale WHERE url = :url;",
                dict(url=url, stale=stale),
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions(StorageError)
    def set_entry_read(
        self, entry: tuple[str, str], read: bool, modified: datetime | None
    ) -> None:
        feed_url, entry_id = entry
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
                    feed_url=feed_url,
                    entry_id=entry_id,
                    read=read,
                    modified=adapt_datetime(modified) if modified else None,
                ),
            )
        rowcount_exactly_one(cursor, lambda: EntryNotFoundError(feed_url, entry_id))

    @wrap_exceptions(StorageError)
    def set_entry_important(
        self, entry: tuple[str, str], important: bool | None, modified: datetime | None
    ) -> None:
        feed_url, entry_id = entry
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
                    modified=adapt_datetime(modified) if modified else None,
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
            (convert_timestamp(r[0]) for r in rows),
            lambda: EntryNotFoundError(feed_url, entry_id),
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
                dict(
                    feed_url=feed_url,
                    entry_id=entry_id,
                    recent_sort=adapt_datetime(recent_sort),
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

        context.update(
            feed._asdict(),
            updated=adapt_datetime(feed.updated) if feed.updated else None,
            last_updated=adapt_datetime(intent.last_updated)
            if intent.last_updated
            else None,
            data_hash=feed.hash,
        )

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
                dict(url=url, last_updated=adapt_datetime(last_updated)),
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
    def add_or_update_entries(self, intents: Iterable[EntryUpdateIntent]) -> None:
        iterables = chunks(self.chunk_size, intents) if self.chunk_size else (intents,)

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

    @wrap_exceptions_iter(StorageError)
    def get_entries(
        self,
        filter: EntryFilter = EntryFilter(),  # noqa: B008
        sort: EntrySort = 'recent',
        limit: int | None = None,
        starting_after: tuple[str, str] | None = None,
    ) -> Iterable[Entry]:
        if sort != 'random':
            return paginated_query(
                self.get_db(),
                partial(_queries.get_entries, filter, sort),
                self.chunk_size,
                limit or 0,
                self.get_entry_last(sort, starting_after) if starting_after else None,
                _queries.entry_factory,
            )
        else:
            return paginated_query(
                self.get_db(),
                partial(_queries.get_entries, filter, sort),
                self.chunk_size,
                min(limit, self.chunk_size) if limit else self.chunk_size,
                row_factory=_queries.entry_factory,
            )

    def get_entry_last(
        self, sort: EntrySort, entry: tuple[str, str]
    ) -> tuple[Any, ...]:
        feed_url, entry_id = entry
        query = (
            Query()
            .SELECT(*_queries.ENTRY_SORT_KEYS[sort])
            .FROM("entries")
            .WHERE("feed = :feed AND id = :id")
        )
        return zero_or_one(
            self.get_db().execute(str(query), dict(feed=feed_url, id=entry_id)),
            lambda: EntryNotFoundError(feed_url, entry_id),
        )

    @wrap_exceptions(StorageError)
    def get_entry_counts(
        self,
        now: datetime,
        filter: EntryFilter = EntryFilter(),  # noqa: B008
    ) -> EntryCounts:
        entries_query = Query().SELECT('id', 'feed').FROM('entries')
        context = _queries.entry_filter(entries_query, filter)

        query, new_context = _queries.get_entry_counts(
            now, self.entry_counts_average_periods, entries_query
        )
        context.update(new_context)

        row = exactly_one(self.get_db().execute(str(query), context))

        return EntryCounts(*row[:4], row[4:7])  # type: ignore[call-arg]

    @wrap_exceptions_iter(StorageError)
    def get_tags(
        self,
        resource_id: AnyResourceId,
        key: str | None = None,
    ) -> Iterable[tuple[str, JSONType]]:
        def make_query() -> tuple[Query, dict[str, Any]]:
            query = Query().SELECT("key")
            context: dict[str, Any] = dict()

            if resource_id is not None:
                info = SCHEMA_INFO[len(resource_id)]
                query.FROM(f"{info.table_prefix}tags")

                if not any(p is None for p in resource_id):
                    query.SELECT("value")
                    for column in info.id_columns:
                        query.WHERE(f"{column} = :{column}")
                    context.update(zip(info.id_columns, resource_id, strict=True))
                else:
                    query.SELECT_DISTINCT("'null'")

            else:
                union = '\nUNION\n'.join(
                    f"SELECT key, value FROM {i.table_prefix}tags"
                    for i in SCHEMA_INFO.values()
                )
                query.with_('tags', union).FROM('tags')
                query.SELECT_DISTINCT("'null'")

            if key is not None:
                query.WHERE("key = :key")
                context.update(key=key)

            query.scrolling_window_order_by("key")

            return query, context

        def row_factory(row: tuple[Any, ...]) -> tuple[str, JSONType]:
            key, value, *_ = row
            return key, json.loads(value)

        return paginated_query(
            self.get_db(),
            make_query,
            self.chunk_size,
            row_factory=row_factory,
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

        params = dict(zip(info.id_columns, resource_id, strict=True), key=key)

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
                {', '.join('?' for _ in columns)}
            )
        """
        params = resource_id + (key,)

        with self.get_db() as db:
            cursor = db.execute(query, params)
        rowcount_exactly_one(cursor, lambda: TagNotFoundError(resource_id, key))


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
        updated=adapt_datetime(entry.updated) if entry.updated else None,
        published=adapt_datetime(entry.published) if entry.published else None,
        last_updated=adapt_datetime(intent.last_updated),
        first_updated=adapt_datetime(intent.first_updated)
        if intent.first_updated
        else None,
        first_updated_epoch=adapt_datetime(intent.first_updated_epoch)
        if intent.first_updated_epoch
        else None,
        recent_sort=adapt_datetime(intent.recent_sort) if intent.recent_sort else None,
        data_hash=entry.hash,
        data_hash_changed=context.pop('hash_changed'),
    )
    return context
