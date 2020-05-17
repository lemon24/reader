import functools
import json
import logging
import random
import sqlite3
import string
import warnings
from collections import OrderedDict
from types import MappingProxyType
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Optional
from typing import Tuple
from typing import TypeVar

from ._sql_utils import Query
from ._sqlite_utils import ddl_transaction
from ._sqlite_utils import json_object_get
from ._sqlite_utils import paginated_query
from ._sqlite_utils import SQLiteType
from ._sqlite_utils import wrap_exceptions
from ._sqlite_utils import wrap_exceptions_iter
from ._storage import apply_filter_options
from ._storage import Storage
from ._types import EntryFilterOptions
from .exceptions import InvalidSearchQueryError
from .exceptions import SearchError
from .exceptions import SearchNotEnabledError
from .types import EntrySearchResult
from .types import HighlightedString


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


class Search:

    """SQLite-storage-bound search provider.

    This is a separate class because conceptually search is not coupled to
    storage (and future search providers may not be).

    See "Do we want to support external search providers in the future?" in
    https://github.com/lemon24/reader/issues/122#issuecomment-591302580
    for details.

    """

    def __init__(self, storage: Storage):
        self.storage = storage

    @property
    def chunk_size(self) -> int:
        return self.storage.get_chunk_size()

    @wrap_exceptions(SearchError)
    def enable(self) -> None:
        try:
            self._enable()
        except sqlite3.OperationalError as e:
            if "table entries_search already exists" in str(e).lower():
                return
            raise

    def _enable(self) -> None:
        with ddl_transaction(self.storage.db) as db:

            # The column names matter, as they can be used in column filters;
            # https://www.sqlite.org/fts5.html#fts5_column_filters
            #
            # We put the unindexed stuff at the end to avoid having to adjust
            # stuff depended on the column index if we add new columns.
            #
            db.execute(
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
            db.execute(
                """
                INSERT INTO entries_search(entries_search, rank)
                VALUES ('rank', 'bm25(4, 1, 2)');
                """
            )

            db.execute(
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
            db.execute(
                """
                INSERT INTO entries_search_sync_state
                SELECT id, feed, 1, 0
                FROM entries;
                """
            )

            # TODO: use "UPDATE OF ... ON" instead;
            # how do we test it?
            # TODO: only run UPDATE triggers if the values are actually different;
            # how do we test it?
            # TODO: what happens if the feed ID changes? can't happen yet;
            # also see https://github.com/lemon24/reader/issues/149

            db.execute(
                """
                CREATE TRIGGER entries_search_entries_insert
                AFTER INSERT ON entries
                BEGIN
                    INSERT INTO entries_search_sync_state
                    VALUES (new.id, new.feed, 1, 0);
                END;
                """
            )
            db.execute(
                """
                CREATE TRIGGER entries_search_entries_update
                AFTER UPDATE ON entries
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
            db.execute(
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
            db.execute(
                """
                CREATE TRIGGER entries_search_feeds_update
                AFTER UPDATE ON feeds
                BEGIN
                    UPDATE entries_search_sync_state
                    SET to_update = 1
                    WHERE new.url = entries_search_sync_state.feed;
                END;
                """
            )

    @wrap_exceptions(SearchError)
    def disable(self) -> None:
        with ddl_transaction(self.storage.db) as db:
            db.execute("DROP TABLE IF EXISTS entries_search;")
            db.execute("DROP TABLE IF EXISTS entries_search_sync_state;")
            db.execute("DROP TRIGGER IF EXISTS entries_search_entries_insert;")
            db.execute("DROP TRIGGER IF EXISTS entries_search_entries_update;")
            db.execute("DROP TRIGGER IF EXISTS entries_search_entries_delete;")
            db.execute("DROP TRIGGER IF EXISTS entries_search_feeds_update;")

    @wrap_exceptions(SearchError)
    def is_enabled(self) -> bool:
        search_table_exists = (
            self.storage.db.execute(
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

        # TODO: is it ok to define the same function many times on the same connection?
        self.storage.db.create_function('strip_html', 1, strip_html)
        self.storage.db.create_function('json_object_get', 2, json_object_get)

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

        # TODO: this loop looks a lot like _utils.join_paginated_iter,
        # minus last and actually yielding stuff

        while True:
            with self.storage.db as db:
                cursor = db.execute(
                    """
                    DELETE FROM entries_search
                    WHERE (_id, _feed) IN (
                        SELECT esss.id, esss.feed
                        FROM entries_search_sync_state AS esss
                        JOIN entries_search ON (esss.id, esss.feed) = (_id, _feed)
                        WHERE to_update OR to_delete
                        LIMIT ?
                    );
                    """,
                    (self.chunk_size or -1,),
                )
                log.debug(
                    'Search.update: _delete_from_search (chunk_size: %s): %s',
                    self.chunk_size,
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
            with self.storage.db as db:
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
        # See the comments in _delete_from_search for
        # why these queries are the way they are.

        input_query = """
            SELECT id, feed
            FROM entries_search_sync_state
            WHERE to_update
            ORDER BY id, feed
            LIMIT ?
        """

        while True:
            with self.storage.db as db:
                cursor = db.execute(
                    f"""
                    INSERT INTO entries_search

                    WITH

                    input(id, feed) AS ({input_query}),

                    from_summary AS (
                        SELECT
                            entries.id,
                            entries.feed,
                            '.summary',
                            strip_html(entries.title),
                            strip_html(entries.summary)
                        FROM input
                        JOIN entries USING (id, feed)
                        WHERE
                            NOT (summary IS NULL OR summary = '')
                    ),

                    from_content AS (
                        SELECT
                            entries.id,
                            entries.feed,
                            '.content[' || json_each.key || '].value',
                            strip_html(entries.title),
                            strip_html(json_object_get(json_each.value, 'value'))
                        FROM input
                        JOIN entries USING (id, feed)
                        JOIN json_each(entries.content)
                        WHERE
                            json_valid(content) and json_array_length(content) > 0
                            -- TODO: test the right content types get indexed
                            AND (
                                json_object_get(json_each.value, 'type') is NULL
                                OR lower(json_object_get(json_each.value, 'type')) in (
                                    'text/html', 'text/xhtml', 'text/plain'
                                )
                            )
                    ),

                    from_default AS (
                        SELECT
                            entries.id,
                            entries.feed,
                            NULL,
                            strip_html(entries.title),
                            NULL
                        FROM input
                        JOIN entries USING (id, feed)
                        WHERE
                            (summary IS NULL OR summary = '')
                            AND (not json_valid(content) OR json_array_length(content) = 0)
                    ),

                    union_all(id, feed, content_path, title, content_text) AS (
                        SELECT * FROM from_summary
                        UNION
                        SELECT * FROM from_content
                        UNION
                        SELECT * FROM from_default
                    )


                    SELECT
                        union_all.title,
                        union_all.content_text,
                        strip_html(coalesce(feeds.user_title, feeds.title)),
                        union_all.id,
                        union_all.feed as feed,
                        union_all.content_path,
                        feeds.user_title IS NOT NULL
                    FROM union_all
                    JOIN feeds ON feeds.url = union_all.feed;

                    """,
                    (self.chunk_size or -1,),
                )
                log.debug(
                    'Search.update: _insert_into_search (insert; chunk_size: %s): %i',
                    self.chunk_size,
                    cursor.rowcount,
                )
                assert cursor.rowcount >= 0

                # Note: We are limiting the number of entries added,
                # not of content pieces (entries_search rows) added.
                # An entry with a lot of contents may still cause this to take
                # a lot of time; it is a problem for later, though, since
                # in practice we don't usually have more than 2 rows per entry.

                # Bail early, there's nothing to update.
                if cursor.rowcount == 0:
                    break

                cursor = db.execute(
                    f"""
                    UPDATE entries_search_sync_state
                    SET to_update = 0
                    WHERE (id, feed) IN ({input_query});
                    """,
                    (self.chunk_size or -1,),
                )
                log.debug(
                    'Search.update: _insert_into_search (set; chunk_size: %s): %i',
                    self.chunk_size,
                    cursor.rowcount,
                )
                assert cursor.rowcount >= 0

                if not self.chunk_size:
                    break
                if cursor.rowcount < self.chunk_size:
                    break

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
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        chunk_size: Optional[int] = None,
        last: Optional[_T] = None,
    ) -> Iterable[Tuple[EntrySearchResult, Optional[_T]]]:

        sql_query = make_search_entries_query(filter_options)

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
                self.storage.db, sql_query, context, value_factory, chunk_size, last
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


def make_search_entries_query(filter_options: EntryFilterOptions,) -> Query:
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

    query.scrolling_window_order_by(
        *"rank search._feed search._id".split(), keyword='HAVING'
    )

    log.debug("_search_entries query\n%s\n", query)

    return query
