from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from functools import partial
from typing import Any
from typing import TYPE_CHECKING

from . import _queries
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
from ..exceptions import StorageError
from ..types import Entry
from ..types import EntryCounts
from ..types import EntrySort
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


log = logging.getLogger('reader')


class EntriesMixin(StorageBase):
    # 1, 3, 12 months rounded down to days,
    # assuming an average of 30.436875 days/month
    entry_counts_average_periods = (30, 91, 365)

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
