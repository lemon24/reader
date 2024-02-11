from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import partial
from typing import Any

from .._types import EntryFilter
from .._types import FeedFilter
from .._types import TagFilter
from ..types import Content
from ..types import Enclosure
from ..types import Entry
from ..types import EntrySort
from ..types import ExceptionInfo
from ..types import Feed
from ..types import FeedSort
from ._sql_utils import BaseQuery
from ._sql_utils import Query


# get_feeds()


def get_feeds(filter: FeedFilter, sort: FeedSort) -> tuple[Query, dict[str, Any]]:
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

    context = feed_filter(query, filter)

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


# get_entries()


def get_entries(filter: EntryFilter, sort: EntrySort) -> tuple[Query, dict[str, Any]]:
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

    filter_context = entry_filter(query, filter)

    if sort == 'recent':
        entries_recent_sort(query)

    elif sort == 'random':
        entries_random_sort(query)

    else:
        assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

    # FIXME: move to Storage
    # log.debug("_get_entries query\n%s\n", query)

    return query, filter_context


def entry_factory(row: tuple[Any, ...]) -> Entry:
    feed = feed_factory(row[0:12])
    (
        id,
        updated,
        title,
        link,
        author,
        published,
        summary,
        content,
        enclosures,
        read,
        read_modified,
        important,
        important_modified,
        first_updated,
        added_by,
        last_updated,
        original_feed,
    ) = row[12:29]
    return Entry(
        id,
        convert_timestamp(updated) if updated else None,
        title,
        link,
        author,
        convert_timestamp(published) if published else None,
        summary,
        tuple(Content(**d) for d in json.loads(content)) if content else (),
        tuple(Enclosure(**d) for d in json.loads(enclosures)) if enclosures else (),
        read == 1,
        convert_timestamp(read_modified) if read_modified else None,
        important == 1 if important is not None else None,
        convert_timestamp(important_modified) if important_modified else None,
        convert_timestamp(first_updated),
        added_by,
        convert_timestamp(last_updated),
        original_feed or feed.url,
        feed,
    )


TRISTATE_FILTER_TO_SQL = dict(
    istrue="({expr} IS NOT NULL AND {expr})",
    isfalse="({expr} IS NOT NULL AND NOT {expr})",
    notset="{expr} IS NULL",
    nottrue="({expr} IS NULL OR NOT {expr})",
    notfalse="({expr} IS NULL OR {expr})",
    isset="{expr} IS NOT NULL",
)


def entry_filter(
    query: Query, filter: EntryFilter, keyword: str = 'WHERE'
) -> dict[str, Any]:
    add = getattr(query, keyword)
    feed_url, entry_id, read, important, has_enclosures, tags, feed_tags = filter

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

    context.update(entry_tags_filter(query, tags, keyword=keyword))
    context.update(feed_tags_filter(query, feed_tags, 'entries.feed', keyword=keyword))

    return context


def feed_tags_filter(
    query: Query, tags: TagFilter, url_column: str, keyword: str = 'WHERE'
) -> dict[str, str]:
    context, tags_cte, tags_count_cte = tags_filter(query, tags, keyword, 'feed_tags')

    if tags_cte:
        query.with_(tags_cte, f"SELECT key FROM feed_tags WHERE feed = {url_column}")

    if tags_count_cte:
        query.with_(
            tags_count_cte,
            f"SELECT count(key) FROM feed_tags WHERE feed = {url_column}",
        )

    return context


def entry_tags_filter(
    query: Query, tags: TagFilter, keyword: str = 'WHERE'
) -> dict[str, str]:
    context, tags_cte, tags_count_cte = tags_filter(query, tags, keyword, 'entry_tags')

    if tags_cte:
        query.with_(
            tags_cte,
            """
            SELECT key FROM entry_tags
            WHERE (id, feed) = (entries.id, entries.feed)
            """,
        )

    if tags_count_cte:
        query.with_(
            tags_count_cte,
            """
            SELECT count(key) FROM entry_tags
            WHERE (id, feed) = (entries.id, entries.feed)
            """,
        )

    return context


def tags_filter(
    query: Query, tags: TagFilter, keyword: str, base_table: str
) -> tuple[dict[str, str], str | None, str | None]:
    add = getattr(query, keyword)

    context = {}

    tags_cte = f'__{base_table}'
    tags_count_cte = f'__{base_table}_count'

    add_tags_cte = False
    add_tags_count_cte = False

    next_tag_id = 0

    for subtags in tags:
        tag_query = BaseQuery({'(': [], ')': ['']}, {'(': 'OR'})
        tag_add = partial(tag_query.add, '(')

        for maybe_tag in subtags:
            if isinstance(maybe_tag, bool):
                tag_add(
                    f"{'NOT' if not maybe_tag else ''} (SELECT * FROM {tags_count_cte})"
                )
                add_tags_count_cte = True
                continue

            is_negation, tag = maybe_tag
            tag_name = f'__{base_table}_{next_tag_id}'
            next_tag_id += 1
            context[tag_name] = tag
            tag_add(f":{tag_name} {'NOT' if is_negation else ''} IN {tags_cte}")
            add_tags_cte = True

        add(str(tag_query))

    return (
        context,
        tags_cte if add_tags_cte else None,
        tags_count_cte if add_tags_count_cte else None,
    )


def entries_recent_sort(
    query: Query, keyword: str = 'WHERE', id_prefix: str = 'entries.'
) -> None:
    """Change query to sort entries by "recent"."""

    # WARNING: Always keep the entries_by_recent index in sync
    # with the ORDER BY of the CTE below.

    query.with_(
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


def entries_random_sort(query: Query) -> None:
    # TODO: "order by random()" always goes through the full result set,
    # which is inefficient; details:
    # https://github.com/lemon24/reader/issues/105#issue-409493128
    #
    # This is a separate function in the hope that search
    # can benefit from future optimizations.
    #
    query.ORDER_BY("random()")


def get_entry_counts(
    now: datetime,
    average_periods: tuple[float, ...],
    entries_query: Query,
) -> tuple[Query, dict[str, Any]]:
    query = (
        Query()
        .with_('entries_filtered', str(entries_query))
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

    context: dict[str, Any] = dict(now=adapt_datetime(now))

    for period_i, period_days in enumerate(average_periods):
        # TODO: when we get first_updated, use it instead of first_updated_epoch

        days_param = f'kfu_{period_i}_days'
        context[days_param] = float(period_days)

        start_param = f'kfu_{period_i}_start'
        context[start_param] = adapt_datetime(now - timedelta(days=period_days))

        kfu_query = (
            Query()
            .SELECT('coalesce(published, updated, first_updated_epoch) AS kfu')
            .FROM('entries_filtered')
            .JOIN("entries USING (id, feed)")
            .GROUP_BY('published, updated, first_updated_epoch, feed')
            .HAVING(f"kfu BETWEEN :{start_param} AND :now")
        )

        query.with_(f'kfu_{period_i}', str(kfu_query))
        query.SELECT(f"(SELECT count(*) / :{days_param} FROM kfu_{period_i})")

    return query, context


# misc


def adapt_datetime(val: datetime) -> str:
    assert val.tzinfo == timezone.utc, val
    val = val.replace(tzinfo=None)
    return val.isoformat(" ")


def convert_timestamp(val: str) -> datetime:
    rv = datetime.fromisoformat(val)
    assert not rv.tzinfo, val
    rv = rv.replace(tzinfo=timezone.utc)
    return rv
