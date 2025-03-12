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
from .._types import FeedToUpdate
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
                    caching_info = NULL,
                    stale = 0,
                    update_after = NULL,
                    last_retrieved = NULL,
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
        sort: FeedSort = FeedSort.TITLE,
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
                caching_info,
                stale,
                last_updated,
                last_exception,
                data_hash,
            ) = row
            return FeedForUpdate(
                url,
                convert_timestamp(updated) if updated else None,
                json.loads(caching_info) if caching_info else None,
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
                    'caching_info',
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
        url, _, _, value = intent

        context: dict[str, Any] = {
            'url': url,
            'last_retrieved': adapt_datetime(intent.last_retrieved),
            'update_after': adapt_datetime(intent.update_after),
        }
        expressions: list[str] = []

        if isinstance(value, FeedToUpdate):
            assert url == value.feed.url, "updating feed URL not supported"

            context.update(
                value._asdict(),
                caching_info=(
                    json.dumps(value.caching_info) if value.caching_info else None
                ),
            )
            feed = context.pop('feed')
            context.update(
                feed._asdict(),
                updated=adapt_datetime(feed.updated) if feed.updated else None,
                last_updated=adapt_datetime(value.last_updated),
                data_hash=feed.hash,
            )
            context.pop('hash', None)

            expressions.append("stale = 0")

        expressions.extend(f"{n} = :{n}" for n in context if n != 'url')

        if isinstance(value, ExceptionInfo):
            context['last_exception'] = json.dumps(value._asdict())
            expressions.append("last_exception = :last_exception")
        else:
            assert isinstance(value, FeedToUpdate | None)
            expressions.append("last_exception = NULL")

        query = f"UPDATE feeds SET {', '.join(expressions)} WHERE url = :url;"

        with self.get_db() as db:
            cursor = db.execute(query, context)

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
            'update_after',
            'last_retrieved',
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
        update_after,
        last_retrieved,
    ) = row[:14]
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
        convert_timestamp(update_after) if update_after else None,
        convert_timestamp(last_retrieved) if last_retrieved else None,
    )


FEED_SORT_KEYS = {
    # values must be non-null, see #203 for details.
    # url at the end makes the order deterministic.
    FeedSort.TITLE: SortKey(
        ("kinda_title", "lower(coalesce(user_title, title, ''))"), "url"
    ),
    FeedSort.ADDED: SortKey("added", "url", desc=True),
}


def feed_filter(query: Query, filter: FeedFilter) -> dict[str, Any]:
    url, tags, broken, updates_enabled, new, update_after = filter

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
        query.WHERE(f"last_retrieved is {'' if new else 'NOT'} NULL")
    if update_after is not None:
        query.WHERE("(update_after is NULL or update_after <= :update_after)")
        context.update(update_after=adapt_datetime(update_after))

    return context
