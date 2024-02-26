from __future__ import annotations

import functools
import json
import logging
import random
import sqlite3
import string
from collections import OrderedDict
from collections.abc import Callable
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime
from functools import partial
from types import MappingProxyType
from typing import Any
from typing import TypeVar

from . import _entries
from . import _sqlite_utils
from . import Storage
from .._types import Action
from .._types import Change
from .._types import EntryFilter
from .._utils import exactly_one
from .._utils import zero_or_one
from ..exceptions import ChangeTrackingNotEnabledError
from ..exceptions import EntryNotFoundError
from ..exceptions import InvalidSearchQueryError
from ..exceptions import SearchError
from ..exceptions import SearchNotEnabledError
from ..types import EntrySearchCounts
from ..types import EntrySearchResult
from ..types import HighlightedString
from ..types import SearchSortOrder
from ._html_utils import strip_html as strip_html_str
from ._sql_utils import paginated_query
from ._sql_utils import Query
from ._sqlite_utils import ddl_transaction
from ._sqlite_utils import SQLiteType


APPLICATION_ID = b'reaD'

_T = TypeVar('_T')


log = logging.getLogger('reader')


@functools.lru_cache
def strip_html(text: SQLiteType) -> SQLiteType:
    if not isinstance(text, str):
        return text
    return strip_html_str(text)


wrap_exceptions = partial(_sqlite_utils.wrap_exceptions, SearchError)

ENABLED_EXC = {'no such table': lambda _: SearchNotEnabledError()}
QUERY_EXC = dict.fromkeys(
    [
        "fts5: syntax error near",
        "unknown special query",
        "no such column",
        "no such cursor",
        "unterminated string",
    ],
    InvalidSearchQueryError,
)


# When trying to fix "database is locked" errors or to optimize stuff,
# have a look at the lessons here first:
# https://github.com/lemon24/reader/issues/175#issuecomment-657495233
# tl;dr: Measure. Measure in prod. FTS5 tables are slow for non-FTS queries.

# When adding a new method, add a new test_search.py::test_errors_locked test.


class Search:

    """Search provider tightly coupled to the SQLite storage.

    Originally done in #122. Updated to use the change tracking API in #323.

    Schema changes related to search must be added to a Storage migration::

        def update_from_X_to_Y(db):
            from ._search import Search

            search = Search(db)

            if search.is_enabled():
                # Using _enable/_disable because we're already in a transaction.

                # This works only if the names of things remain the same.
                # Otherwise, the queries from the previous version's disable()
                # need to be copied verbatim.
                search.disable()

                search.enable()

    Example: https://github.com/lemon24/reader/blob/f0894d93d8573680c656335ded46ebcf482cf7cd/src/reader/_storage.py#L146

    """

    def __init__(self, storage: Storage):
        self.storage = storage
        self.path = None
        self.schema = 'main'
        if not storage.factory.is_private():
            self.path = storage.factory.path + '.search'
            self.schema = 'search'
            with wrap_exceptions(message="while opening database"):
                # not using the storage connection because PyPy doesn't like it
                # (see _sqlite_utils.setup_db() for details)
                with closing(sqlite3.connect(self.path)) as db:
                    self.setup_db(db)
                storage.factory.attach(self.schema, self.path)

    def get_db(self) -> sqlite3.Connection:
        return self.storage.factory()

    @staticmethod
    def setup_db(db: sqlite3.Connection) -> None:
        _sqlite_utils.setup_db(db, id=APPLICATION_ID)

    @staticmethod
    def strip_html(text: SQLiteType) -> SQLiteType:
        # strip_html is not part of the Search interface,
        # but is part of the private API of this implementation.
        return strip_html(text)  # type: ignore[no-any-return]

    @wrap_exceptions()
    def enable(self) -> None:
        self.storage.changes.enable()
        try:
            with ddl_transaction(self.get_db()) as db:
                self._enable(db, self.schema)
        except sqlite3.OperationalError as e:
            if "table entries_search already exists" in str(e).lower():
                return
            else:  # pragma: no cover
                raise

    @classmethod
    def _enable(cls, db: sqlite3.Connection, schema: str = 'main') -> None:
        # Private API, may be called from migrations.

        assert db.in_transaction

        # The column names matter, as they can be used in column filters;
        # https://www.sqlite.org/fts5.html#fts5_column_filters
        #
        # We put the unindexed stuff at the end to avoid having to adjust
        # stuff depended on the column index if we add new columns.
        #
        db.execute(
            f"""
            CREATE VIRTUAL TABLE {schema}.entries_search USING fts5(
                title,  -- entries.title
                content,  -- entries.summary or one of entries.content
                feed,  -- feeds.title or feed.user_title
                _id UNINDEXED,
                _feed UNINDEXED,
                _content_path UNINDEXED,  -- TODO: maybe optimize this to a number
                _is_feed_user_title UNINDEXED,
                tokenize = "porter unicode61 remove_diacritics 1 tokenchars '_'"
            );
            """
        )
        # TODO: we still need to tune the rank weights, these are just guesses
        db.execute(
            """
            INSERT INTO entries_search(entries_search, rank)
            VALUES ('rank', 'bm25(4, 1, 2)');
            """
        )

        db.execute(
            f"""
            CREATE TABLE {schema}.entries_search_sync_state (
                sequence BLOB NOT NULL,
                feed TEXT NOT NULL,
                id TEXT NOT NULL,
                es_rowids TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (sequence, feed, id)
            );
            """
        )

    @wrap_exceptions()
    def disable(self) -> None:
        self.storage.changes.disable()

        db = self.get_db()
        with ddl_transaction(db):
            self._disable(db)

        # I don't know how to delete the search database correctly
        # while it's attached to other connections.
        #
        # For example, if I delete the database from connection A,
        # B can still use it, even the file is not visible on disk;
        # then, new connection C will create a new database,
        # while B still points to the old one.
        #
        # So, it's best to leave deleting the files to the user,
        # who can guarantee no connections actually use them anymore.
        #
        # However, we at least minimize the space they take using VACUUM.

        if self.path:
            db.execute("VACUUM search;")

    @classmethod
    def _disable(cls, db: sqlite3.Connection) -> None:
        # Private API, may be called from migrations.
        assert db.in_transaction
        db.execute("DROP TABLE IF EXISTS entries_search;")
        db.execute("DROP TABLE IF EXISTS entries_search_sync_state;")

    @wrap_exceptions()
    def is_enabled(self) -> bool:
        return self._is_enabled(self.get_db())

    @staticmethod
    def _is_enabled(db: sqlite3.Connection) -> bool:
        # Private API, may be called from migrations.
        try:
            list(db.execute("SELECT * FROM entries_search LIMIT 0;"))
        except sqlite3.OperationalError as e:
            if "no such table: entries_search" in str(e):
                return False
            else:  # pragma: no cover
                raise
        else:
            return True

    @wrap_exceptions(ENABLED_EXC)
    def update(self) -> None:
        try:
            self._delete_from_search()
            self._insert_into_search()
        except ChangeTrackingNotEnabledError as e:
            raise SearchNotEnabledError() from e

    def _delete_from_search(self) -> None:
        # The loop is done outside of the chunk logic to help testing.
        while changes := self.storage.changes.get(Action.DELETE):
            self._delete_from_search_one_chunk(changes)
            self.storage.changes.done(changes)

    def _delete_from_search_one_chunk(self, changes: list[Change]) -> None:
        with self.get_db() as db:
            for change in changes:
                # ignore non-entry changes
                if not (
                    change.feed_url and change.entry_id and not change.tag_key
                ):  # pragma: no cover
                    continue
                assert change.action == Action.DELETE, change.action

                db.execute(
                    """
                    DELETE FROM entries_search WHERE rowid IN (
                        SELECT value
                        FROM entries_search_sync_state AS ss
                        JOIN json_each(es_rowids)
                        WHERE (ss.sequence, ss.feed, ss.id) = (?, ?, ?)
                    )
                    """,
                    (change.sequence, change.feed_url, change.entry_id),
                )
                db.execute(
                    """
                    DELETE FROM entries_search_sync_state
                    WHERE (sequence, feed, id) = (?, ?, ?)
                    """,
                    (change.sequence, change.feed_url, change.entry_id),
                )

        log.debug("Search.update: _delete_from_search: chunk done")

    def _insert_into_search(self) -> None:
        # The loop is done outside of the chunk logic to help testing.
        while changes := self.storage.changes.get(Action.INSERT):
            self._insert_into_search_one_chunk(changes)
            self.storage.changes.done(changes)

    def _insert_into_search_one_chunk(self, changes: list[Change]) -> None:
        # We don't call strip_html() in transactions,
        # because it keeps the database locked for too long.
        #
        # Before reader 3.11, the search index was in the main database,
        # and the list of changes would be recorded using triggers.
        # Before reader 1.4 / #175, updates were done in a single transaction,
        # which made the "database locked" issue visibly bad.
        #
        # Since 3.11, the search index is in a separate, attached database,
        # so we don't care about locking that one that much.
        # https://gist.github.com/lemon24/c57b3772ed5a36aabfe723df9820d6bc

        # split in a separate loop in preparation for future optimization
        # https://github.com/lemon24/reader/issues/323#issuecomment-1930756417
        entries = {}
        for change in changes:
            # ignore non-entry changes
            if not (
                change.feed_url and change.entry_id and not change.tag_key
            ):  # pragma: no cover
                continue
            assert change.action == Action.INSERT, change.action
            entry = next(
                iter(
                    self.storage.get_entries(
                        EntryFilter(change.feed_url, change.entry_id), limit=1
                    )
                ),
                None,
            )
            if not entry:  # pragma: no cover FIXME: needs test
                continue
            if entry._sequence != change.sequence:
                continue
            entries[change] = entry

        stripped = {}
        for change, entry in entries.items():
            final: list[tuple[str, str] | tuple[None, None]] = []

            for i, content in enumerate(entry.content):
                if (content.type or '').lower() not in (
                    '',
                    'text/html',
                    'text/xhtml',
                    'text/plain',
                ):
                    continue
                final.append((self.strip_html(content.value), f'.content[{i}].value'))

            if entry.summary:
                final.append((self.strip_html(entry.summary), '.summary'))

            if not final:
                final.append((None, None))

            stripped_title = self.strip_html(entry.title or '')
            feed_title = entry.feed.user_title or entry.feed.title or ''
            is_feed_user_title = bool(entry.feed.user_title)
            stripped_feed_title = self.strip_html(feed_title)

            stripped[change] = [
                dict(
                    title=stripped_title,
                    content=content_value,
                    feed=stripped_feed_title,
                    _id=entry.id,
                    _feed=entry.feed_url,
                    _content_path=content_path,
                    _is_feed_user_title=is_feed_user_title,
                )
                for content_value, content_path in final
            ]

        for change, group in stripped.items():
            with self.get_db() as db:
                # SELECT does not acquire a lock, use BEGIN IMMEDIATE
                # to do so if the first statement is not a DML one.

                cursor = db.execute(
                    """
                    DELETE FROM entries_search WHERE rowid IN (
                        SELECT value
                        FROM entries_search_sync_state AS ss
                        JOIN json_each(es_rowids)
                        WHERE (ss.sequence, ss.feed, ss.id) = (?, ?, ?)
                    )
                    """,
                    (change.sequence, change.feed_url, change.entry_id),
                )
                if cursor.rowcount:  # pragma: no cover
                    log.warn(
                        "during insert, found and deleted %d rows for %r",
                        cursor.rowcount,
                        change,
                    )

                new_es_rowids = []
                for params in group:
                    cursor = db.execute(
                        """
                        INSERT INTO entries_search
                        VALUES (
                            :title,
                            :content,
                            :feed,
                            :_id,
                            :_feed,
                            :_content_path,
                            :_is_feed_user_title
                        );
                        """,
                        params,
                    )
                    new_es_rowids.append(cursor.lastrowid)

                db.execute(
                    """
                    INSERT OR REPLACE INTO entries_search_sync_state
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        change.sequence,
                        change.feed_url,
                        change.entry_id,
                        json.dumps(new_es_rowids),
                    ),
                )

        log.debug("Search.update: _insert_into_search: chunk done")

    def search_entries(
        self,
        query: str,
        filter: EntryFilter = EntryFilter(),  # noqa: B008
        sort: SearchSortOrder = 'relevant',
        limit: int | None = None,
        starting_after: tuple[str, str] | None = None,
    ) -> Iterable[EntrySearchResult]:
        random_mark = ''.join(
            random.choices(string.ascii_letters + string.digits, k=20)
        )
        before_mark = f'>>>{random_mark}>>>'
        after_mark = f'<<<{random_mark}<<<'

        def make_query() -> tuple[Query, dict[str, Any]]:
            sql_query, context = make_search_entries_query(filter, sort)
            context.update(
                query=query,
                before_mark=before_mark,
                after_mark=after_mark,
                # 255 letters / 4.7 letters per word (average in English)
                snippet_tokens=54,
            )
            return sql_query, context

        row_factory = partial(
            entry_search_result_factory,
            before_mark=before_mark,
            after_mark=after_mark,
        )

        chunk_size = self.storage.chunk_size

        def pq(
            limit: int | None, last: tuple[Any, ...] | None = None
        ) -> Iterable[EntrySearchResult]:
            with wrap_exceptions(ENABLED_EXC | QUERY_EXC):
                yield from paginated_query(
                    self.get_db(),
                    make_query,
                    chunk_size,
                    limit or 0,
                    last,
                    row_factory,
                )

        # TODO: dupe of at least Storage.get_entries(), maybe deduplicate
        if sort != 'random':
            last = None
            if starting_after:
                if sort == 'relevant':
                    last = self.search_entry_last(query, starting_after)
                elif sort == 'recent':
                    last = self.storage.get_entry_last(sort, starting_after)
                else:
                    assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

            return pq(limit, last)

        else:
            return pq(min(limit, chunk_size) if limit else chunk_size)

    @wrap_exceptions(ENABLED_EXC)
    def search_entry_last(self, query: str, entry: tuple[str, str]) -> tuple[Any, ...]:
        feed_url, entry_id = entry

        sql_query = (
            Query()
            .SELECT('min(rank)', '_feed', '_id')
            .FROM("entries_search")
            .WHERE("entries_search MATCH :query")
            .WHERE("_feed = :feed AND _id = :id")
            .GROUP_BY('_feed', '_id')
        )

        context = dict(feed=feed_url, id=entry_id, query=query)

        return zero_or_one(
            self.get_db().execute(str(sql_query), context),
            lambda: EntryNotFoundError(feed_url, entry_id),
        )

    @wrap_exceptions(ENABLED_EXC | QUERY_EXC)
    def search_entry_counts(
        self,
        query: str,
        now: datetime,
        filter: EntryFilter = EntryFilter(),  # noqa: B008
    ) -> EntrySearchCounts:
        entries_query = (
            Query()
            .with_(
                "search",
                """
                    SELECT _id, _feed
                    FROM entries_search
                    WHERE entries_search MATCH :query
                    GROUP BY _id, _feed
                    """,
            )
            .SELECT('id', 'feed')
            .FROM('entries')
            .JOIN("search ON (id, feed) = (_id, _feed)")
        )
        query_context = _entries.entry_filter(entries_query, filter)

        sql_query, new_context = _entries.get_entry_counts_query(
            now, self.storage.entry_counts_average_periods, entries_query
        )
        query_context.update(new_context)

        context = dict(query=query, **query_context)
        row = exactly_one(self.get_db().execute(str(sql_query), context))
        return EntrySearchCounts(*row[:4], row[4:7])  # type: ignore[call-arg]


def make_search_entries_query(
    filter: EntryFilter, sort: SearchSortOrder
) -> tuple[Query, dict[str, Any]]:
    search = (
        Query()
        .SELECT(
            """
            _id,
            _feed,
            rank,
            snippet(
                entries_search, 0, :before_mark, :after_mark, '...',
                :snippet_tokens
            ) AS title,
            snippet(
                entries_search, 2, :before_mark, :after_mark, '...',
                :snippet_tokens
            ) AS feed,
            _is_feed_user_title AS is_feed_user_title,
            json_object(
                'path', _content_path,
                'value', snippet(
                    entries_search, 1,
                    :before_mark, :after_mark, '...', :snippet_tokens
                ),
                'rank', rank
            ) AS content
            """
        )
        .FROM("entries_search")
        .JOIN("entries ON (entries.id, entries.feed) = (_id, _feed)")
        .WHERE("entries_search MATCH :query")
        .ORDER_BY("rank")
        # https://www.mail-archive.com/sqlite-users@mailinglists.sqlite.org/msg115821.html
        # rule 14 https://www.sqlite.org/optoverview.html#subquery_flattening
        .LIMIT("-1 OFFSET 0")
    )

    context = _entries.entry_filter(search, filter)

    query = (
        Query()
        .with_("search", str(search))
        .SELECT(
            "search._id",
            "search._feed",
            ("rank", "min(search.rank)"),
            "search.title",
            "search.feed",
            "search.is_feed_user_title",
            "json_group_array(json(search.content))",
        )
        .FROM("search")
        .GROUP_BY("search._id", "search._feed")
    )
    SEARCH_ENTRIES_SORT[sort](query)

    log.debug("_search_entries query\n%s\n", query)

    return query, context


def relevant_sort(query: Query) -> None:
    query.scrolling_window_order_by(
        'rank', 'search._feed', 'search._id', keyword='HAVING'
    )


SEARCH_ENTRIES_SORT: dict[str, Callable[[Query], None]] = {
    'relevant': relevant_sort,
    'recent': partial(
        _entries.entries_recent_sort, keyword='HAVING', id_prefix='search._'
    ),
    'random': _entries.entries_random_sort,
}


def entry_search_result_factory(
    t: tuple[Any, ...], before_mark: str, after_mark: str
) -> EntrySearchResult:
    (
        entry_id,
        feed_url,
        rank,
        title,
        feed_title,
        is_feed_user_title,
        content,
        *_,
    ) = t
    content = json.loads(content)

    metadata = {}
    if title:
        metadata['.title'] = HighlightedString.extract(title, before_mark, after_mark)
    if feed_title:
        metadata[
            '.feed.title' if not is_feed_user_title else '.feed.user_title'
        ] = HighlightedString.extract(feed_title, before_mark, after_mark)

    rv_content: dict[str, HighlightedString] = OrderedDict(
        (
            c['path'],
            HighlightedString.extract(c['value'], before_mark, after_mark),
        )
        for c in content
        if c['path']
    )

    return EntrySearchResult(
        feed_url,
        entry_id,
        MappingProxyType(metadata),
        MappingProxyType(rv_content),
    )
