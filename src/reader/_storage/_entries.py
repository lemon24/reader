from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from collections.abc import Iterable
from datetime import datetime
from datetime import timedelta
from functools import partial
from typing import Any
from typing import TYPE_CHECKING

from .._types import EntryFilter
from .._types import EntryForUpdate
from .._types import EntryUpdateIntent
from .._utils import chunks
from .._utils import exactly_one
from .._utils import zero_or_one
from ..exceptions import EntryError
from ..exceptions import EntryExistsError
from ..exceptions import EntryNotFoundError
from ..exceptions import FeedNotFoundError
from ..types import Content
from ..types import Enclosure
from ..types import Entry
from ..types import EntryCounts
from ..types import EntrySort
from ..types import EntrySource
from ._base import wrap_exceptions
from ._feeds import feed_factory
from ._sql_utils import Query
from ._sql_utils import SortKey
from ._sqlite_utils import adapt_datetime
from ._sqlite_utils import convert_timestamp
from ._sqlite_utils import rowcount_exactly_one
from ._tags import entry_tags_filter
from ._tags import feed_tags_filter


if TYPE_CHECKING:  # pragma: no cover
    from ._base import StorageBase
else:
    StorageBase = object


log = logging.getLogger('reader')


class EntriesMixin(StorageBase):
    # 1, 3, 12 months rounded down to days,
    # assuming an average of 30.436875 days/month
    entry_counts_average_periods = (30, 91, 365)

    def get_entries(
        self,
        filter: EntryFilter = EntryFilter(),  # noqa: B008
        sort: EntrySort = EntrySort.RECENT,
        limit: int | None = None,
        starting_after: tuple[str, str] | None = None,
    ) -> Iterable[Entry]:
        paginated_query = partial(
            self.paginated_query,
            partial(get_entries_query, filter, sort),
            row_factory=entry_factory,
        )
        if sort != EntrySort.RANDOM:
            last = self.get_entry_last(sort, starting_after) if starting_after else None
            return paginated_query(limit, last)
        else:
            limit = min(limit, self.chunk_size) if limit else self.chunk_size
            return paginated_query(limit)

    @wrap_exceptions()
    def get_entry_last(
        self, sort: EntrySort, entry: tuple[str, str]
    ) -> tuple[Any, ...]:
        feed_url, entry_id = entry
        query = (
            Query()
            .SELECT(*ENTRY_SORT_KEYS[sort])
            .FROM("entries")
            .WHERE("feed = :feed AND id = :id")
        )
        return zero_or_one(
            self.get_db().execute(str(query), dict(feed=feed_url, id=entry_id)),
            lambda: EntryNotFoundError(feed_url, entry_id),
        )

    @wrap_exceptions()
    def get_entry_counts(
        self,
        now: datetime,
        filter: EntryFilter = EntryFilter(),  # noqa: B008
    ) -> EntryCounts:
        entries_query = Query().SELECT('id', 'feed').FROM('entries')
        context = entry_filter(entries_query, filter)

        query, new_context = get_entry_counts_query(
            now, self.entry_counts_average_periods, entries_query
        )
        context.update(new_context)

        row = exactly_one(self.get_db().execute(str(query), context))
        return EntryCounts(*row[:5], row[5:8])  # type: ignore[call-arg]

    @wrap_exceptions()
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

    @wrap_exceptions()
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

    def get_entries_for_update(
        self, entries: Iterable[tuple[str, str]]
    ) -> Iterable[EntryForUpdate | None]:
        with wrap_exceptions():
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
            fu, fu_epoch, recent_sort, updated, data_hash, data_hash_changed = row
            return EntryForUpdate(
                convert_timestamp(fu),
                convert_timestamp(fu_epoch),
                convert_timestamp(recent_sort),
                convert_timestamp(updated) if updated else None,
                data_hash,
                data_hash_changed,
            )

        query = """
            SELECT
                first_updated,
                first_updated_epoch,
                recent_sort,
                updated,
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

    @wrap_exceptions()
    def add_or_update_entries(self, intents: Iterable[EntryUpdateIntent]) -> None:
        iterables = chunks(self.chunk_size, intents) if self.chunk_size else (intents,)

        # It's acceptable for this to not be atomic (only some of the entries
        # may be updated if we get an exception), since they will likely
        # be updated on the next update (because the feed will not be marked
        # as updated if there's an exception, so we get a free retry).
        for iterable in iterables:
            self._add_or_update_entries(iterable)

    def _add_or_update_entries(self, intents: Iterable[EntryUpdateIntent]) -> None:
        with self.get_db() as db:
            try:
                for intent in intents:
                    # we cannot rely on the updater getting an EntryForUpdate
                    # to tell if the entry is new at *this* point in time,
                    # the entry may have been added/deleted by a parallel update
                    #
                    # as a consequence, EntryUpdateIntent must set all fields,
                    # including the ones which have a single value
                    # for the entire lifetime of the entry (like first_updated)

                    new = not list(
                        db.execute(
                            "SELECT 1 FROM entries WHERE (feed, id) = (?, ?)",
                            intent.entry.resource_id,
                        )
                    )

                    if new:
                        self._insert_entry(db, intent)
                    else:
                        self._update_entry(db, intent)

            except sqlite3.IntegrityError as e:
                e_msg = str(e).lower()
                if "foreign key constraint failed" in e_msg:
                    raise FeedNotFoundError(intent.entry.feed_url) from None
                raise  # pragma: no cover

    def _insert_entry(self, db: sqlite3.Connection, intent: EntryUpdateIntent) -> None:
        query = """
            INSERT INTO entries (
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
                source,
                read,
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
                :source,
                0,  -- read (should be not null in the schema, but isn't)
                :last_updated,
                :first_updated,
                :first_updated_epoch,
                :feed_order,
                :recent_sort,
                :original_feed,
                :data_hash,
                :data_hash_changed,
                :added_by
            );
        """
        db.execute(query, entry_update_intent_to_dict(intent))

    def _update_entry(self, db: sqlite3.Connection, intent: EntryUpdateIntent) -> None:
        query = """
            UPDATE entries
            SET
                title = :title,
                link = :link,
                updated = :updated,
                author = :author,
                published = :published,
                summary = :summary,
                content = :content,
                enclosures = :enclosures,
                source = :source,
                last_updated = :last_updated,
                feed_order = :feed_order,
                recent_sort = :recent_sort,
                original_feed = :original_feed,
                data_hash = :data_hash,
                data_hash_changed = :data_hash_changed,
                added_by = :added_by
            WHERE (feed, id) = (:feed_url, :id)
        """
        db.execute(query, entry_update_intent_to_dict(intent))

    def add_or_update_entry(self, intent: EntryUpdateIntent) -> None:
        # TODO: this method is for testing convenience only, maybe delete it?
        self.add_or_update_entries([intent])

    @wrap_exceptions()
    def add_entry(self, intent: EntryUpdateIntent) -> None:
        with self.get_db() as db:
            try:
                self._insert_entry(db, intent)
            except sqlite3.IntegrityError as e:
                e_msg = str(e).lower()
                if "foreign key constraint failed" in e_msg:
                    raise FeedNotFoundError(intent.entry.feed_url) from None
                if "unique constraint failed: entries.id, entries.feed" in e_msg:
                    raise EntryExistsError(*intent.entry.resource_id) from None
                raise  # pragma: no cover

    @wrap_exceptions()
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

    @wrap_exceptions()
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

    @wrap_exceptions()
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


def get_entries_query(
    filter: EntryFilter, sort: EntrySort
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
            feeds.update_after
            feeds.last_retrieved
            entries.id
            entries.updated
            entries.title
            entries.link
            entries.author
            entries.published
            entries.summary
            entries.content
            entries.enclosures
            entries.source
            entries.read
            entries.read_modified
            entries.important
            entries.important_modified
            entries.first_updated
            entries.added_by
            entries.last_updated
            entries.original_feed
            entries.sequence
            """.split()
        )
        .FROM("entries")
        .JOIN("feeds ON feeds.url = entries.feed")
    )
    context = entry_filter(query, filter)
    ENTRIES_SORT[sort](query)
    return query, context


def entry_factory(row: tuple[Any, ...]) -> Entry:
    feed = feed_factory(row[0:14])
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
        source,
        read,
        read_modified,
        important,
        important_modified,
        first_updated,
        added_by,
        last_updated,
        original_feed,
        sequence,
    ) = row[14:33]

    source_obj = None
    if source:
        source_dict = json.loads(source)
        if source_dict['updated']:
            source_dict['updated'] = convert_timestamp(source_dict['updated'])
        source_obj = EntrySource(**source_dict)

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
        source_obj,
        read == 1,
        convert_timestamp(read_modified) if read_modified else None,
        important == 1 if important is not None else None,
        convert_timestamp(important_modified) if important_modified else None,
        convert_timestamp(first_updated),
        added_by,
        convert_timestamp(last_updated),
        original_feed or feed.url,
        sequence,
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
    feed_url, entry_id, read, important, has_enclosures, source_url, tags, feed_tags = (
        filter
    )

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

    if source_url:
        add("json_extract(entries.source, '$.url') = :source_url")
        context['source_url'] = source_url

    context.update(entry_tags_filter(query, tags, keyword=keyword))
    context.update(feed_tags_filter(query, feed_tags, 'entries.feed', keyword=keyword))

    return context


RECENT_SORT_KEY = SortKey(
    # keep this in sync with the entries_by_recent.
    # values must be non-null, see #203 for details.
    # id at the end makes the order deterministic.
    'recent_sort',
    ('kinda_published', 'coalesce(published, updated, first_updated)'),
    'feed',
    'last_updated',
    ('negative_feed_order', '- feed_order'),
    'id',
    desc=True,
)

ENTRY_SORT_KEYS = {EntrySort.RECENT: RECENT_SORT_KEY}


def entries_recent_sort(
    query: Query, keyword: str = 'WHERE', id_prefix: str = 'entries.'
) -> None:
    ids_query = Query().FROM('entries').scrolling_window_sort_key(RECENT_SORT_KEY)
    query.with_('ids', str(ids_query))
    query.JOIN(f"ids ON (ids.id, ids.feed) = ({id_prefix}id, {id_prefix}feed)")

    ids_names = RECENT_SORT_KEY.names('ids.')
    query.SELECT(*ids_names)
    query.scrolling_window_order_by(*ids_names, desc=True, keyword=keyword)


def entries_random_sort(query: Query) -> None:
    # TODO: "order by random()" always goes through the full result set,
    # which is inefficient; details:
    # https://github.com/lemon24/reader/issues/105#issue-409493128
    #
    # This is a separate function in the hope that search
    # can benefit from future optimizations.
    #
    query.ORDER_BY("random()")


ENTRIES_SORT: dict[EntrySort, Callable[[Query], None]] = {
    EntrySort.RECENT: entries_recent_sort,
    EntrySort.RANDOM: entries_random_sort,
}


def get_entry_counts_query(
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
            'coalesce(sum(important == 0), 0)',
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


def entry_update_intent_to_dict(intent: EntryUpdateIntent) -> dict[str, Any]:
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
        first_updated=(
            adapt_datetime(intent.first_updated) if intent.first_updated else None
        ),
        first_updated_epoch=(
            adapt_datetime(intent.first_updated_epoch)
            if intent.first_updated_epoch
            else None
        ),
        recent_sort=adapt_datetime(intent.recent_sort) if intent.recent_sort else None,
        original_feed=intent.original_feed_url,
        data_hash=entry.hash,
        data_hash_changed=context.pop('hash_changed'),
    )

    if entry.source:
        source_dict = entry.source._asdict()
        if entry.source.updated:
            source_dict['updated'] = adapt_datetime(entry.source.updated)
        context['source'] = json.dumps(source_dict)

    return context
