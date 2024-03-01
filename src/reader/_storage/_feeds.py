from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from functools import partial
from typing import Any
from typing import TYPE_CHECKING

from .._types import FeedFilter
from .._types import FeedForUpdate
from .._types import FeedUpdateIntent
from .._utils import exactly_one
from .._utils import zero_or_one
from ..exceptions import FeedExistsError
from ..exceptions import FeedNotFoundError
from ..types import ExceptionInfo
from ..types import Feed
from ..types import FeedCounts
from ..types import FeedSort
from ._base import wrap_exceptions
from ._sql_utils import Query
from ._sql_utils import SortKey
from ._sqlite_utils import adapt_datetime
from ._sqlite_utils import convert_timestamp
from ._sqlite_utils import rowcount_exactly_one
from ._tags import feed_tags_filter

if TYPE_CHECKING:  # pragma: no cover
    from ._base import StorageBase
else:
    StorageBase = object


class FeedsMixin(StorageBase):
    @wrap_exceptions()
    def add_feed(self, url: str, added: datetime) -> None:
        with self.get_db() as db:
            try:
                db.execute(
                    "INSERT INTO feeds (url, added) VALUES (:url, :added);",
                    dict(url=url, added=adapt_datetime(added)),
                )
            except sqlite3.IntegrityError as e:
                e_msg = str(e).lower()
                if "unique constraint failed: feeds.url" in e_msg:
                    raise FeedExistsError(url) from None
                raise  # pragma: no cover

    @wrap_exceptions()
    def delete_feed(self, url: str) -> None:
        with self.get_db() as db:
            cursor = db.execute("DELETE FROM feeds WHERE url = :url;", dict(url=url))
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions()
    def change_feed_url(self, old: str, new: str) -> None:
        with self.get_db() as db:
            try:
                cursor = db.execute(
                    "UPDATE feeds SET url = :new WHERE url = :old;",
                    dict(old=old, new=new),
                )
            except sqlite3.IntegrityError as e:
                e_msg = str(e).lower()
                if "unique constraint failed: feeds.url" in e_msg:
                    raise FeedExistsError(new) from None
                raise  # pragma: no cover
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
        filter: FeedFilter = FeedFilter(),  # noqa: B008
        sort: FeedSort = 'title',
        limit: int | None = None,
        starting_after: str | None = None,
    ) -> Iterable[Feed]:
        return self.paginated_query(
            partial(get_feeds_query, filter, sort),
            limit,
            self.get_feed_last(sort, starting_after) if starting_after else None,
            feed_factory,
        )

    @wrap_exceptions()
    def get_feed_last(self, sort: FeedSort, url: str) -> tuple[Any, ...]:
        query = (
            Query()
            .SELECT(*FEED_SORT_KEYS[sort])
            .FROM("feeds")
            .WHERE("url = :url")
        )  # fmt: skip
        return zero_or_one(
            self.get_db().execute(str(query), dict(url=url)),
            lambda: FeedNotFoundError(url),
        )

    @wrap_exceptions()
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

        context = feed_filter(query, filter)

        row = exactly_one(self.get_db().execute(str(query), context))

        return FeedCounts(*row)

    @wrap_exceptions()
    def set_feed_user_title(self, url: str, title: str | None) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                "UPDATE feeds SET user_title = :title WHERE url = :url;",
                dict(url=url, title=title),
            )
        rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions()
    def set_feed_updates_enabled(self, url: str, enabled: bool) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                "UPDATE feeds SET updates_enabled = :updates_enabled WHERE url = :url;",
                dict(url=url, updates_enabled=enabled),
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

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
            context = feed_filter(query, filter)
            return query, context

        return self.paginated_query(make_query, row_factory=row_factory)

    @wrap_exceptions()
    def set_feed_stale(self, url: str, stale: bool) -> None:
        with self.get_db() as db:
            cursor = db.execute(
                "UPDATE feeds SET stale = :stale WHERE url = :url;",
                dict(url=url, stale=stale),
            )
            rowcount_exactly_one(cursor, lambda: FeedNotFoundError(url))

    @wrap_exceptions()
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


def get_feeds_query(filter: FeedFilter, sort: FeedSort) -> tuple[Query, dict[str, Any]]:
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
        .scrolling_window_sort_key(FEED_SORT_KEYS[sort])
    )
    context = feed_filter(query, filter)
    return query, context


def feed_factory(row: tuple[Any, ...]) -> Feed:
    (
        url,
        updated,
        title,
        link,
        author,
        subtitle,
        version,
        user_title,
        added,
        last_updated,
        last_exception,
        updates_enabled,
    ) = row[:12]
    return Feed(
        url,
        convert_timestamp(updated) if updated else None,
        title,
        link,
        author,
        subtitle,
        version,
        user_title,
        convert_timestamp(added),
        convert_timestamp(last_updated) if last_updated else None,
        ExceptionInfo(**json.loads(last_exception)) if last_exception else None,
        updates_enabled == 1,
    )


FEED_SORT_KEYS = {
    # values must be non-null, see #203 for details.
    # url at the end makes the order deterministic.
    'title': SortKey(("kinda_title", "lower(coalesce(user_title, title, ''))"), "url"),
    'added': SortKey("added", "url", desc=True),
}


def feed_filter(query: Query, filter: FeedFilter) -> dict[str, Any]:
    url, tags, broken, updates_enabled, new = filter

    context: dict[str, object] = {}

    if url:
        query.WHERE("url = :url")
        context.update(url=url)

    context.update(feed_tags_filter(query, tags, 'feeds.url'))

    if broken is not None:
        query.WHERE(f"last_exception IS {'NOT' if broken else ''} NULL")
    if updates_enabled is not None:
        query.WHERE(f"{'' if updates_enabled else 'NOT'} updates_enabled")
    if new is not None:
        query.WHERE(f"last_updated is {'' if new else 'NOT'} NULL")

    return context
