import functools
import json
import logging
import random
import sqlite3
import string
import warnings
from collections import OrderedDict
from datetime import datetime
from datetime import timedelta
from itertools import groupby
from types import MappingProxyType
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Tuple
from typing import TypeVar
from typing import Union

from ._sql_utils import Query
from ._sqlite_utils import ddl_transaction
from ._sqlite_utils import paginated_query
from ._sqlite_utils import SQLiteType
from ._sqlite_utils import wrap_exceptions
from ._sqlite_utils import wrap_exceptions_iter
from ._storage import apply_filter_options
from ._storage import apply_recent
from ._storage import Storage
from ._types import EntryFilterOptions
from .exceptions import InvalidSearchQueryError
from .exceptions import SearchError
from .exceptions import SearchNotEnabledError
from .types import EntrySearchResult
from .types import HighlightedString
from .types import SearchSortOrder


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


# When trying to fix "database is locked" errors or to optimize stuff,
# have a look at the lessons here first:
# https://github.com/lemon24/reader/issues/175#issuecomment-657495233


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

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.get_chunk_size: Callable[[], int] = lambda: 256
        self.get_recent_threshold: Callable[
            [], timedelta
        ] = lambda: Storage.recent_threshold

    # chunk_size and strip_html are not part of the Search interface,
    # but are part of the private API of this implementation
    # to allow overriding during tests.

    @property
    def chunk_size(self) -> int:
        return self.get_chunk_size()

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
                PRIMARY KEY (id, feed)
            );
            """
        )
        # TODO: This should probably be paginated,
        # but it's called once and should not take too long, so we can do it later.
        self.db.execute(
            """
            INSERT INTO entries_search_sync_state
            SELECT id, feed, 1, 0
            FROM entries;
            """
        )

    def _create_triggers(self) -> None:
        # Private API, may be called from migrations.

        assert self.db.in_transaction

        # TODO: what happens if the feed ID changes? can't happen yet;
        # also see https://github.com/lemon24/reader/issues/149

        self.db.execute(
            """
            CREATE TRIGGER entries_search_entries_insert
            AFTER INSERT ON entries
            BEGIN
                INSERT INTO entries_search_sync_state
                VALUES (new.id, new.feed, 1, 0);
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
                raise SearchNotEnabledError() from e
            raise

    def _update(self) -> None:
        # If bs4 is not available, we raise an exception here, otherwise
        # we get just a "user-defined function raised exception" SearchError.
        if not bs4:
            raise SearchError(
                "could not import search dependencies; "
                "use the 'search' extra to install them; "
                f"original import error: {bs4_import_error}"
            ) from bs4_import_error

        # FIXME: how do we test pagination?
        self._delete_from_search()
        self._delete_from_sync_state()
        self._insert_into_search()

    def _delete_from_search(self) -> None:
        # Some notes about why these queries are the way they are:
        #
        # SQLite doesn't support DELETE-FROM-JOIN, so we can't use that.
        #
        # We could use DELETE-LIMIT, but the Windows and macOS official
        # Python build SQLite does not have ENABLE_UPDATE_DELETE_LIMIT;
        # https://www.sqlite.org/lang_delete.html
        #
        # Due to a bug in the Python sqlite3 binding, cursor.rowcount is -1
        # if the query does not start with INSERT/UPDATE/DELETE;
        # this means no CTEs or comments should precede the keyword;
        # https://bugs.python.org/issue35398, https://bugs.python.org/issue36859
        #
        # Alternatively, we can use the changes() SQL function instead
        # (this always works);
        # https://www.sqlite.org/lang_corefunc.html#changes

        if self.chunk_size:
            # `DELETE FROM entries_search` may be slower than other queries,
            # so we use smaller chunks to avoid keeping locks for too long.
            # https://github.com/lemon24/reader/issues/175#issuecomment-656112990
            chunk_size = max(1, int(self.chunk_size / 16))
        else:
            chunk_size = self.chunk_size

        # TODO: is the join required? it results in 2 entries_search scans instead of 1

        while True:
            with self.db as db:
                cursor = db.execute(
                    """
                    DELETE FROM entries_search
                    WHERE (_id, _feed) IN (
                        SELECT id, feed
                        FROM entries_search_sync_state
                        WHERE to_delete
                        LIMIT ?
                    );
                    """,
                    (chunk_size or -1,),
                )
                log.debug(
                    'Search.update: _delete_from_search (chunk_size: %s): %s',
                    chunk_size,
                    cursor.rowcount,
                )
                assert cursor.rowcount >= 0

                if not self.chunk_size:
                    break

                # Each entries_search_sync_state row should have
                # at least one correponding row in entries_search.
                # This means that rowcount may be greater than chunk_size
                # (not a problem), even if there are no rows left to delete
                # (also not a problem, there will be an additional query
                # that deletes 0 rows).
                if cursor.rowcount < self.chunk_size:
                    break

    def _delete_from_sync_state(self) -> None:
        # See the comments in _delete_from_search for
        # why these queries are the way they are.

        while True:
            with self.db as db:
                cursor = db.execute(
                    """
                    DELETE
                    FROM entries_search_sync_state
                    WHERE (id, feed) IN (
                        SELECT id, feed
                        FROM entries_search_sync_state
                        WHERE to_delete
                        LIMIT ?
                    );
                    """,
                    (self.chunk_size or -1,),
                )

            log.debug(
                'Search.update: _delete_from_sync_state (chunk_size: %s): %s',
                self.chunk_size,
                cursor.rowcount,
            )
            assert cursor.rowcount >= 0

            if not self.chunk_size:
                break
            if cursor.rowcount < self.chunk_size:
                break

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

                to_update = db.execute(
                    """
                    SELECT to_update
                    FROM entries_search_sync_state
                    WHERE (id, feed) = (?, ?);
                    """,
                    (id, feed_url),
                ).fetchone()
                if not (to_update and to_update[0]):
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
                db.execute(
                    "DELETE FROM entries_search WHERE (_id, _feed) = (?, ?)",
                    (id, feed_url),
                )

                db.executemany(
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
                    group,
                )

                db.execute(
                    """
                    UPDATE entries_search_sync_state
                    SET to_update = 0
                    WHERE (id, feed) = (?, ?);
                    """,
                    (id, feed_url),
                )

        log.debug("Search.update: _insert_into_search: chunk done")
        return True

    _query_error_message_fragments = [
        "fts5: syntax error near",
        "unknown special query",
        "no such column",
        "no such cursor",
        "unterminated string",
    ]

    @wrap_exceptions_iter(SearchError)
    def search_entries(
        self,
        query: str,
        now: datetime,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        sort: SearchSortOrder = 'relevant',
        chunk_size: Optional[int] = None,
        last: Optional[_T] = None,
    ) -> Iterable[Tuple[EntrySearchResult, Optional[_T]]]:

        sql_query = make_search_entries_query(filter_options, sort)

        random_mark = ''.join(
            random.choices(string.ascii_letters + string.digits, k=20)
        )
        before_mark = f'>>>{random_mark}>>>'
        after_mark = f'<<<{random_mark}<<<'

        context = dict(
            query=query,
            **filter_options._asdict(),
            before_mark=before_mark,
            after_mark=after_mark,
            # 255 letters / 4.7 letters per word (average in English)
            snippet_tokens=54,
            recent_threshold=now - self.get_recent_threshold(),
        )

        def value_factory(t: Tuple[Any, ...]) -> EntrySearchResult:
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
                metadata['.title'] = HighlightedString.extract(
                    title, before_mark, after_mark
                )
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

        try:
            yield from paginated_query(
                self.db, sql_query, context, value_factory, chunk_size, last
            )

        except sqlite3.OperationalError as e:
            msg_lower = str(e).lower()

            if 'no such table' in msg_lower:
                raise SearchNotEnabledError() from e

            is_query_error = any(
                fragment in msg_lower
                for fragment in self._query_error_message_fragments
            )
            if is_query_error:
                raise InvalidSearchQueryError(str(e)) from e

            raise


def make_search_entries_query(
    filter_options: EntryFilterOptions, sort: SearchSortOrder
) -> Query:
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

    apply_filter_options(search, filter_options)

    query = (
        Query()
        .WITH(("search", search.to_str(end='')))
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
        query.JOIN("entries ON (entries.id, entries.feed) = (_id, _feed)")
        apply_recent(query, keyword='HAVING', id_prefix='search._')
    else:
        assert False, "shouldn't get here"  # noqa: B011; # pragma: no cover

    log.debug("_search_entries query\n%s\n", query)

    return query
