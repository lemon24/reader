import functools
import json
import logging
import random
import sqlite3
import string
import warnings
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta
from functools import partial
from itertools import groupby
from types import MappingProxyType
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Optional
from typing import Tuple
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import Union

from ._sql_utils import paginated_query
from ._sql_utils import Query
from ._sqlite_utils import DBError
from ._sqlite_utils import ddl_transaction
from ._sqlite_utils import require_version
from ._sqlite_utils import SQLiteType
from ._sqlite_utils import wrap_exceptions
from ._sqlite_utils import wrap_exceptions_iter
from ._storage import apply_entry_filter_options
from ._storage import apply_random
from ._storage import apply_recent
from ._storage import Storage
from ._types import EntryFilterOptions
from ._utils import exactly_one
from ._utils import join_paginated_iter
from ._utils import zero_or_one
from .exceptions import EntryNotFoundError
from .exceptions import InvalidSearchQueryError
from .exceptions import SearchError
from .exceptions import SearchNotEnabledError
from .types import EntrySearchCounts
from .types import EntrySearchResult
from .types import HighlightedString
from .types import SearchSortOrder

if TYPE_CHECKING:  # pragma: no cover
    from ._storage import Storage  # noqa: F401


# Only Search.update() has a reason to fail if bs4 is missing.
try:
    import bs4  # type: ignore

    bs4_import_error = None
except ImportError as e:  # pragma: no cover
    bs4 = None
    bs4_import_error = e

log = logging.getLogger('reader')


_T = TypeVar('_T')


# BeautifulSoup warns if not giving it a parser explicitly; full text:
#
#   No parser was explicitly specified, so I'm using the best available
#   HTML parser for this system ("..."). This usually isn't a problem,
#   but if you run this code on another system, or in a different virtual
#   environment, it may use a different parser and behave differently.
#
# We are ok with any parser, and with how BeautifulSoup picks the best one if
# available. Explicitly using generic features (e.g. `('html', 'fast')`,
# the default) instead of a specific parser still warns.
#
# Currently there's no way to allow users to pick a parser, and we don't want
# to force a specific parser, so there's no point in warning.
#
# When changing this, also change the equivalent pytest.filterwarnings config.
#
# TODO: Expose BeautifulSoup(features=...) when we have a config system.
#
warnings.filterwarnings(
    'ignore', message='No parser was explicitly specified', module='reader._search'
)


@functools.lru_cache()
def strip_html(text: SQLiteType, features: Optional[str] = None) -> SQLiteType:
    if not isinstance(text, str):
        return text

    soup = bs4.BeautifulSoup(text, features=features)

    # <script>, <noscript> and <style> don't contain things relevant to search.
    # <title> probably does, but its content should already be in the entry title.
    #
    # Although <head> is supposed to contain machine-readable content, Firefox
    # shows any free-floating text it contains, so we should keep it around.
    #
    for e in soup.select('script, noscript, style, title'):
        e.replace_with('\n')

    rv = soup.get_text(separator=' ')
    # TODO: Remove this assert once bs4 gets type annotations.
    assert isinstance(rv, str)

    return rv


_QUERY_ERROR_MESSAGE_FRAGMENTS = [
    "fts5: syntax error near",
    "unknown special query",
    "no such column",
    "no such cursor",
    "unterminated string",
]


@contextmanager
def wrap_search_exceptions() -> Iterator[None]:
    try:
        yield
    except sqlite3.OperationalError as e:
        msg_lower = str(e).lower()

        if 'no such table' in msg_lower:
            raise SearchNotEnabledError()

        is_query_error = any(
            fragment in msg_lower for fragment in _QUERY_ERROR_MESSAGE_FRAGMENTS
        )
        if is_query_error:
            raise InvalidSearchQueryError(message=str(e))

        raise


# When trying to fix "database is locked" errors or to optimize stuff,
# have a look at the lessons here first:
# https://github.com/lemon24/reader/issues/175#issuecomment-657495233

# When adding a new method, add a new test_search.py::test_errors_locked test.


class Search:

    """Search provider tightly coupled to the SQLite storage.

    This is a separate class because conceptually search is not coupled to
    storage (and future/alternative search providers may not be).

    See "Do we want to support external search providers in the future?" in
    https://github.com/lemon24/reader/issues/122#issuecomment-591302580
    for details.

    Schema changes related to search must be added to a Storage migration::

        def update_from_X_to_Y(db):
            from ._search import Search

            search = Search(db)

            if search.is_enabled():
                # We're already within a transaction, we use _enable/_disable,
                # not enable/disable.
                # Or, we can selectively call some of the _drop_*/_create_*
                # methods (e.g. to only re-create triggers)

                # This works only if the names of things remain the same.
                # Otherwise, the queries from the previous version's disable()
                # need to be copied verbatim.
                search.disable()

                search.enable()

    Example: https://github.com/lemon24/reader/blob/f0894d93d8573680c656335ded46ebcf482cf7cd/src/reader/_storage.py#L146

    Also see "How does this interact with migrations?" in
    https://github.com/lemon24/reader/issues/122#issuecomment-591302580

    """

    def __init__(self, storage: Union['Storage', sqlite3.Connection]):
        # during migrations there's no storage, so we need to pass the DB in
        self.storage = storage

    # db, recent_threshold, and chunk_size exposed for convenience.

    @property
    def db(self) -> sqlite3.Connection:
        if isinstance(self.storage, sqlite3.Connection):  # pragma: no cover
            return self.storage
        return self.storage.db

    @property
    def recent_threshold(self) -> timedelta:
        if isinstance(self.storage, sqlite3.Connection):  # pragma: no cover
            raise NotImplementedError(
                f"self.storage is {self.storage!r}, should be Storage"
            )
        return self.storage.recent_threshold

    @property
    def chunk_size(self) -> int:
        if isinstance(self.storage, sqlite3.Connection):  # pragma: no cover
            raise NotImplementedError(
                f"self.storage is {self.storage!r}, should be Storage"
            )
        return self.storage.chunk_size

    # strip_html is not part of the Search interface,
    # but is part of the private API of this implementation.
    strip_html = staticmethod(strip_html)

    @wrap_exceptions(SearchError)
    def enable(self) -> None:
        try:
            with ddl_transaction(self.db):
                self._enable()
        except sqlite3.OperationalError as e:
            if "table entries_search already exists" in str(e).lower():
                return
            raise

    def _enable(self) -> None:
        # Private API, may be called from migrations.
        self._create_tables()
        self._create_triggers()

    def _create_tables(self) -> None:
        # Private API, may be called from migrations.

        assert self.db.in_transaction

        # The column names matter, as they can be used in column filters;
        # https://www.sqlite.org/fts5.html#fts5_column_filters
        #
        # We put the unindexed stuff at the end to avoid having to adjust
        # stuff depended on the column index if we add new columns.
        #
        self.db.execute(
            """
            CREATE VIRTUAL TABLE entries_search USING fts5(
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
        # FIXME: we still need to tune the rank weights, these are just guesses
        self.db.execute(
            """
            INSERT INTO entries_search(entries_search, rank)
            VALUES ('rank', 'bm25(4, 1, 2)');
            """
        )

        self.db.execute(
            """
            CREATE TABLE entries_search_sync_state (
                id TEXT NOT NULL,
                feed TEXT NOT NULL,
                to_update INTEGER NOT NULL DEFAULT 1,
                to_delete INTEGER NOT NULL DEFAULT 0,
                es_rowids TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (id, feed)
            );
            """
        )
        # TODO: This should probably be paginated,
        # but it's called once and should not take too long, so we can do it later.
        self.db.execute(
            """
            INSERT INTO entries_search_sync_state (id, feed)
            SELECT id, feed
            FROM entries;
            """
        )

    def _create_triggers(self) -> None:
        # Private API, may be called from migrations.

        assert self.db.in_transaction

        # We can't use just "INSERT INTO entries_search_sync_state (id, feed)",
        # because this trigger also gets called in case of
        # "INSERT OR REPLACE INTO entries" (REPLACE = DELETE + INSERT),
        # which would wipe out es_rowids.
        #
        # Per https://www.sqlite.org/lang_conflict.html,
        # the ON DELETE trigger doesn't fire during REPLACE
        # if recursive_triggers are not enabled (they aren't, as of 1.5).
        #
        # What I don't understand is why the "INSERT into esss" below succeeds
        # even when a specific (id, feed) already exists in esss
        # (it seems to act as INSERT OR REPLACE -- maybe because it already
        # is in one, and that REPLACE is global?).
        # Anyway, it seems to do what we need it to do.

        self.db.execute(
            """
            CREATE TRIGGER entries_search_entries_insert
            AFTER INSERT ON entries
            BEGIN
                INSERT INTO entries_search_sync_state (id, feed, es_rowids)
                VALUES (
                    new.id,
                    new.feed,
                    (
                        SELECT es_rowids
                        from entries_search_sync_state
                        where (id, feed) = (new.id, new.feed)
                    )
                );
            END;
            """
        )
        self.db.execute(
            """
            CREATE TRIGGER entries_search_entries_update
            AFTER UPDATE

            OF title, summary, content
            ON entries
            WHEN
                new.title != old.title
                OR new.summary != old.summary
                OR new.content != old.content

            BEGIN
                UPDATE entries_search_sync_state
                SET to_update = 1
                WHERE (new.id, new.feed) = (
                    entries_search_sync_state.id,
                    entries_search_sync_state.feed
                );
            END;
            """
        )
        self.db.execute(
            """
            CREATE TRIGGER entries_search_entries_delete
            AFTER DELETE ON entries
            BEGIN
                UPDATE entries_search_sync_state
                SET to_delete = 1
                WHERE (old.id, old.feed) = (
                    entries_search_sync_state.id,
                    entries_search_sync_state.feed
                );
            END;
            """
        )

        # No need to do anything for added feeds, since they don't have
        # any entries. No need to do anything for deleted feeds, since
        # the entries delete trigger will take care of its entries.
        self.db.execute(
            """
            CREATE TRIGGER entries_search_feeds_update
            AFTER UPDATE

            OF title, user_title
            ON feeds
            WHEN
                new.title != old.title
                OR new.user_title != old.user_title

            BEGIN
                UPDATE entries_search_sync_state
                SET to_update = 1
                WHERE new.url = entries_search_sync_state.feed;
            END;
            """
        )

        # We must delete stuff from the old feed early, before update().
        # Otherwise, if the old feed was just deleted and had an entry
        # with the same id as one from the new feed, we'll get an
        # "UNIQUE constraint failed" for esss(id, feed)
        # when we update esss.feed to new.url.
        self.db.execute(
            """
            CREATE TRIGGER entries_search_feeds_update_url
            AFTER UPDATE

            OF url ON feeds
            WHEN new.url != old.url

            BEGIN
                DELETE FROM entries_search
                WHERE rowid IN (
                    SELECT value
                    FROM entries_search_sync_state
                    JOIN json_each(es_rowids)
                    WHERE feed = new.url AND to_delete = 1
                );
                DELETE FROM entries_search_sync_state
                WHERE feed = new.url AND to_delete = 1;

                UPDATE entries_search
                SET _feed = new.url
                WHERE rowid IN (
                    SELECT value
                    FROM entries_search_sync_state
                    JOIN json_each(es_rowids)
                    WHERE feed = old.url
                );
                UPDATE entries_search_sync_state
                SET feed = new.url
                WHERE feed = old.url;

            END;
            """
        )

    @wrap_exceptions(SearchError)
    def disable(self) -> None:
        with ddl_transaction(self.db):
            self._disable()

    def _disable(self) -> None:
        # Private API, may be called from migrations.
        self._drop_triggers()
        self._drop_tables()

    def _drop_tables(self) -> None:
        # Private API, may be called from migrations.
        assert self.db.in_transaction
        self.db.execute("DROP TABLE IF EXISTS entries_search;")
        self.db.execute("DROP TABLE IF EXISTS entries_search_sync_state;")

    def _drop_triggers(self) -> None:
        # Private API, may be called from migrations.
        assert self.db.in_transaction
        self.db.execute("DROP TRIGGER IF EXISTS entries_search_entries_insert;")
        self.db.execute("DROP TRIGGER IF EXISTS entries_search_entries_update;")
        self.db.execute("DROP TRIGGER IF EXISTS entries_search_entries_delete;")
        self.db.execute("DROP TRIGGER IF EXISTS entries_search_feeds_update;")
        self.db.execute("DROP TRIGGER IF EXISTS entries_search_feeds_update_url;")

    @wrap_exceptions(SearchError)
    def is_enabled(self) -> bool:
        search_table_exists = (
            self.db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'entries_search';
                """
            ).fetchone()
            is not None
        )
        return search_table_exists

    @wrap_exceptions(SearchError)
    def update(self) -> None:
        try:
            return self._update()
        except sqlite3.OperationalError as e:
            if 'no such table' in str(e).lower():
                raise SearchNotEnabledError()
            raise

    def _update(self) -> None:
        # If bs4 is not available, we raise an exception here, otherwise
        # we get just a "user-defined function raised exception" SearchError.
        if not bs4:
            raise SearchError(
                message="could not import search dependencies "
                "(use the 'search' extra to install them)"
            ) from bs4_import_error

        # last_insert_rowid() / cursor.lastrowid works correctly for FTS5
        # tables only starting with SQLite 3.18.
        # https://www.sqlite.org/releaselog/3_18_0.html
        try:
            require_version(self.db, (3, 18))
        except DBError as e:
            raise SearchError(message=str(e))

        self._delete_from_search()
        self._insert_into_search()

    def _delete_from_search(self) -> None:
        done = False
        while not done:
            done = not self._delete_from_search_one_chunk()

    def _delete_from_search_one_chunk(self) -> bool:
        # if it's not chunked, it's one by one;
        # we can't / don't want to pull all the entries into memory
        chunk_size = self.chunk_size or 1

        with self.db as db:
            # See _insert_into_search_one_chunk for why we're doing this.
            db.execute('BEGIN IMMEDIATE;')

            # TODO: maybe use a single cursor

            rows = list(
                db.execute(
                    """
                    SELECT id, feed, es_rowids
                    FROM entries_search_sync_state
                    WHERE to_delete
                    LIMIT ?;
                    """,
                    (chunk_size,),
                )
            )

            first_entry = (rows[0][1], rows[0][0]) if rows else None
            log.debug(
                "Search.update: _delete_from_search (chunk_size: %s): "
                "got %s entries; first entry: %r",
                self.chunk_size,
                len(rows),
                first_entry,
            )

            if not rows:
                # nothing to delete
                return False

            # it may be possible to delete all of them in a single query,
            # but because we're using SQLite (and they execute locally),
            # we're not gonna bother

            db.executemany(
                "DELETE FROM entries_search WHERE rowid = ?;",
                ((id,) for row in rows for id in json.loads(row[2])),
            )
            db.executemany(
                "DELETE FROM entries_search_sync_state WHERE (id, feed) = (?, ?);",
                (row[:2] for row in rows),
            )

            if len(rows) < chunk_size:
                # no results left (at least when nothing else happens in parallel)
                return False

        log.debug("Search.update: _delete_from_search: chunk done")
        return True

    def _insert_into_search(self) -> None:
        # The loop is done outside of the chunk logic to help testing.
        done = False
        while not done:
            done = not self._insert_into_search_one_chunk()

    def _insert_into_search_one_chunk(self) -> bool:
        # We don't call strip_html() in transactions, because it keeps
        # the database locked for too long; instead, we:
        #
        # * pull a bunch of entry content into Python (one transaction),
        # * strip HTML outside of a transaction, and then
        # * update each entry and clear entries_search_sync_state,
        #   but only if it still needs to be updated,
        #   and its last_updated didn't change (another transaction).
        #
        # Before reader 1.4, we would insert the data from entries
        # into entries_search in a single INSERT statement
        # (with stripping HTML taking ~90% of the time)
        # and then clear entries_search_sync_state,
        # all in a single transaction.
        #
        # The advantage was that entries could not be updated while
        # updating search (because the database was locked);
        # now it *can* happen, and we must not clear entries_search_sync_state
        # if it did (we rely on last_updated for this).
        #
        # See this comment for pseudocode of both approaches:
        # https://github.com/lemon24/reader/issues/175#issuecomment-652489019

        rows = list(
            self.db.execute(
                """
                SELECT
                    entries.id,
                    entries.feed,
                    entries.last_updated,
                    esss.es_rowids,
                    coalesce(feeds.user_title, feeds.title),
                    feeds.user_title IS NOT NULL,
                    entries.title,
                    entries.summary,
                    entries.content
                FROM entries_search_sync_state AS esss
                JOIN entries USING (id, feed)
                JOIN feeds ON feeds.url = esss.feed
                WHERE esss.to_update
                LIMIT ?
                """,
                # if it's not chunked, it's one by one;
                # we can't / don't want to pull all the entries into memory
                (self.chunk_size or 1,),
            )
        )

        first_entry = (rows[0][1], rows[0][0]) if rows else None
        log.debug(
            "Search.update: _insert_into_search (chunk_size: %s): "
            "got %s entries; first entry: %r",
            self.chunk_size,
            len(rows),
            first_entry,
        )

        if not rows:
            # nothing to update
            return False

        stripped: List[Dict[str, Any]] = []
        for (
            id,
            feed_url,
            last_updated,
            es_rowids_json,
            feed_title,
            is_feed_user_title,
            title,
            summary,
            content_json,
        ) in rows:
            final: List[Union[Tuple[str, str], Tuple[None, None]]] = []

            content = json.loads(content_json) if content_json else []
            if content and isinstance(content, list):
                for i, content_dict in enumerate(content):
                    if (content_dict.get('type') or '').lower() not in (
                        '',
                        'text/html',
                        'text/xhtml',
                        'text/plain',
                    ):
                        continue

                    final.append(
                        (
                            self.strip_html(content_dict.get('value')),
                            f'.content[{i}].value',
                        )
                    )

            if summary:
                final.append((self.strip_html(summary), '.summary'))

            if not final:
                final.append((None, None))

            stripped_title = self.strip_html(title)
            stripped_feed_title = self.strip_html(feed_title)

            stripped.extend(
                dict(
                    title=stripped_title,
                    content=content_value,
                    feed=stripped_feed_title,
                    _id=id,
                    _feed=feed_url,
                    _content_path=content_path,
                    _is_feed_user_title=is_feed_user_title,
                    _last_updated=last_updated,
                    _es_rowids=json.loads(es_rowids_json),
                )
                for content_value, content_path in final
            )

        # presumably we could insert everything in a single transaction,
        # but we'd have to throw everything away if just one entry changed;
        # https://github.com/lemon24/reader/issues/175#issuecomment-653535994

        groups = groupby(stripped, lambda d: (d['_id'], d['_feed']))
        for (id, feed_url), group_iter in groups:
            group = list(group_iter)
            with self.db as db:
                # With the default isolation mode, a BEGIN is emitted
                # only when a DML statement is executed (I think);
                # this means that any SELECTs aren't actually
                # inside of a transaction; this is a DBAPI2 (mis)feature.
                #
                # BEGIN IMMEDIATE acquires a write lock immediately;
                # this will fail now, or will succeed and none
                # of the following statements until COMMIT/ROLLBACK
                # can fail with "database is locked".
                # We can't use a plain BEGIN (== DEFFERED), since
                # it delays acquiring a write lock until the first write
                # statement (the insert).
                #
                db.execute('BEGIN IMMEDIATE;')

                # TODO: maybe use a single cursor
                # TODO: these two checks look very cumbersome, make them easier to read

                to_update = db.execute(
                    """
                    SELECT to_update, es_rowids
                    FROM entries_search_sync_state
                    WHERE (id, feed) = (?, ?);
                    """,
                    (id, feed_url),
                ).fetchone()
                if not (
                    to_update
                    and to_update[0]
                    and set(json.loads(to_update[1])) == set(group[0]['_es_rowids'])
                ):
                    # a concurrent call updated this entry, skip it
                    log.debug(
                        "Search.update: _insert_into_search: "
                        "entry already updated, skipping: %r",
                        (feed_url, id),
                    )
                    continue

                last_updated = db.execute(
                    "SELECT last_updated FROM entries WHERE (id, feed) = (?, ?);",
                    (id, feed_url),
                ).fetchone()
                if not last_updated or last_updated[0] != group[0]['_last_updated']:
                    # last_updated changed since we got it;
                    # skip the entry, we'll catch it on the next loop
                    log.debug(
                        "Search.update: _insert_into_search: "
                        "entry last_updated changed, skipping: %r",
                        (feed_url, id),
                    )
                    continue

                # we can't rely on _delete_from_search doing it,
                # since a parallel update may have added some rows since then
                # (and we'd duplicate them)
                db.executemany(
                    "DELETE FROM entries_search WHERE rowid = ?;",
                    ((id,) for id in group[0]['_es_rowids']),
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
                    UPDATE entries_search_sync_state
                    SET to_update = 0, es_rowids = ?
                    WHERE (id, feed) = (?, ?);
                    """,
                    (json.dumps(new_es_rowids), id, feed_url),
                )

        log.debug("Search.update: _insert_into_search: chunk done")
        return True

    def search_entries(
        self,
        query: str,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        sort: SearchSortOrder = 'relevant',
        limit: Optional[int] = None,
        starting_after: Optional[Tuple[str, str]] = None,
    ) -> Iterable[EntrySearchResult]:
        # TODO: dupe of at least Storage.get_entries(), maybe deduplicate
        if sort in ('relevant', 'recent'):

            last = None
            if starting_after:
                if sort == 'recent':
                    assert isinstance(self.storage, Storage)
                    last = self.storage.get_entry_last(now, sort, starting_after)
                else:
                    last = self.search_entry_last(query, starting_after)

            rv = join_paginated_iter(
                partial(self.search_entries_page, query, now, filter_options, sort),  # type: ignore[arg-type]
                self.chunk_size,
                last,
                limit or 0,
            )

        elif sort == 'random':
            assert not starting_after
            it = self.search_entries_page(
                query,
                now,
                filter_options,
                sort,
                min(limit, self.chunk_size or limit) if limit else self.chunk_size,
            )
            rv = (entry for entry, _ in it)

        else:
            assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

        yield from rv

    @wrap_exceptions(SearchError)
    def search_entry_last(self, query: str, entry: Tuple[str, str]) -> Tuple[Any, ...]:
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
            self.db.execute(str(sql_query), context),
            lambda: EntryNotFoundError(feed_url, entry_id),
        )

    @wrap_exceptions_iter(SearchError)
    def search_entries_page(
        self,
        query: str,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        sort: SearchSortOrder = 'relevant',
        chunk_size: Optional[int] = None,
        last: Optional[_T] = None,
    ) -> Iterable[Tuple[EntrySearchResult, Optional[_T]]]:

        sql_query, context = make_search_entries_query(filter_options, sort)

        random_mark = ''.join(
            random.choices(string.ascii_letters + string.digits, k=20)
        )
        before_mark = f'>>>{random_mark}>>>'
        after_mark = f'<<<{random_mark}<<<'

        context.update(
            query=query,
            before_mark=before_mark,
            after_mark=after_mark,
            # 255 letters / 4.7 letters per word (average in English)
            snippet_tokens=54,
            recent_threshold=now - self.recent_threshold,
        )

        row_factory = partial(
            entry_search_result_factory,
            before_mark=before_mark,
            after_mark=after_mark,
        )

        with wrap_search_exceptions():
            yield from paginated_query(
                self.db, sql_query, context, chunk_size, last, row_factory
            )

    @wrap_exceptions(SearchError)
    @wrap_search_exceptions()
    def search_entry_counts(
        self,
        query: str,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
    ) -> EntrySearchCounts:
        sql_query, query_context = make_search_entry_counts_query(filter_options)
        context = dict(query=query, **query_context)
        row = exactly_one(self.db.execute(str(sql_query), context))
        return EntrySearchCounts(*row)


def make_search_entries_query(
    filter_options: EntryFilterOptions, sort: SearchSortOrder
) -> Tuple[Query, Dict[str, Any]]:
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

    context = apply_entry_filter_options(search, filter_options)

    query = (
        Query()
        .WITH(("search", str(search)))
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

    if sort == 'relevant':
        query.scrolling_window_order_by(
            *"rank search._feed search._id".split(), keyword='HAVING'
        )
    elif sort == 'recent':
        apply_recent(query, keyword='HAVING', id_prefix='search._')
    elif sort == 'random':
        apply_random(query)
    else:
        assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

    log.debug("_search_entries query\n%s\n", query)

    return query, context


def entry_search_result_factory(
    t: Tuple[Any, ...], before_mark: str, after_mark: str
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

    rv_content: Dict[str, HighlightedString] = OrderedDict(
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


def make_search_entry_counts_query(
    filter_options: EntryFilterOptions,
) -> Tuple[Query, Dict[str, Any]]:
    query = (
        Query()
        .WITH(
            (
                "search",
                """
                SELECT _id, _feed
                FROM entries_search
                WHERE entries_search MATCH :query
                GROUP BY _id, _feed
                """,
            )
        )
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
        .FROM("entries")
        .JOIN("search ON (id, feed) = (_id, _feed)")
    )

    context = apply_entry_filter_options(query, filter_options)

    return query, context
