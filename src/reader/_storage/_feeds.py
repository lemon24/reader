from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from functools import partial
from typing import Any
from typing import TYPE_CHECKING

from . import _queries
from .._types import FeedFilter
from .._types import FeedForUpdate
from .._types import FeedUpdateIntent
from .._utils import exactly_one
from .._utils import zero_or_one
from ..exceptions import FeedExistsError
from ..exceptions import FeedNotFoundError
from ..exceptions import StorageError
from ..types import ExceptionInfo
from ..types import Feed
from ..types import FeedCounts
from ..types import FeedSort
from ._queries import adapt_datetime
from ._queries import convert_timestamp
from ._sql_utils import paginated_query
from ._sql_utils import Query
from ._sqlite_utils import rowcount_exactly_one
from ._sqlite_utils import wrap_exceptions
from ._sqlite_utils import wrap_exceptions_iter

if TYPE_CHECKING:  # pragma: no cover
    from ._base import StorageBase
else:
    StorageBase = object


class FeedsMixin(StorageBase):
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

    @wrap_exceptions(StorageError)
    def set_feed_stale(self, url: str, stale: bool) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                "UPDATE feeds SET stale = :stale WHERE url = :url;",
                dict(url=url, stale=stale),
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

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
