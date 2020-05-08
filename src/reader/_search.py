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
from typing import cast
from typing import Dict
from typing import Iterable
from typing import Optional
from typing import Tuple
from typing import TypeVar

from ._sql_utils import Query  # type: ignore
from ._sqlite_utils import ddl_transaction
from ._sqlite_utils import json_object_get
from ._sqlite_utils import wrap_exceptions
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


_SqliteType = TypeVar('_SqliteType', None, int, float, str, bytes)


@functools.lru_cache()
def strip_html(text: _SqliteType, features: Optional[str] = None) -> _SqliteType:
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


_SearchEntriesLast = Optional[Tuple[Any, Any, Any]]


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

        with self.storage.db as db:
            db.execute(
                """
                -- SQLite doesn't support DELETE-FROM-JOIN
                DELETE FROM entries_search
                WHERE
                    (_id, _feed) IN (
                        SELECT id, feed
                        FROM entries_search_sync_state
                        WHERE to_update OR to_delete
                    )
                ;
                """
            )
            db.execute(
                """
                DELETE FROM entries_search_sync_state
                WHERE to_delete;
                """
            )
            db.execute(
                """
                WITH

                from_summary AS (
                    SELECT
                        entries.id,
                        entries.feed,
                        '.summary',
                        strip_html(entries.title),
                        strip_html(entries.summary)
                    FROM entries_search_sync_state
                    JOIN entries USING (id, feed)
                    WHERE
                        entries_search_sync_state.to_update
                        AND NOT (summary IS NULL OR summary = '')
                ),

                from_content AS (
                    SELECT
                        entries.id,
                        entries.feed,
                        '.content[' || json_each.key || '].value',
                        strip_html(entries.title),
                        strip_html(json_object_get(json_each.value, 'value'))
                    FROM entries_search_sync_state
                    JOIN entries USING (id, feed)
                    JOIN json_each(entries.content)
                    WHERE
                        entries_search_sync_state.to_update
                        AND json_valid(content) and json_array_length(content) > 0
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
                    FROM entries_search_sync_state
                    JOIN entries USING (id, feed)
                    WHERE
                        entries_search_sync_state.to_update
                        AND (summary IS NULL OR summary = '')
                        AND (not json_valid(content) OR json_array_length(content) = 0)
                ),

                union_all(id, feed, content_path, title, content_text) AS (
                    SELECT * FROM from_summary
                    UNION
                    SELECT * FROM from_content
                    UNION
                    SELECT * FROM from_default
                )

                INSERT INTO entries_search

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

                """
            )
            db.execute(
                """
                UPDATE entries_search_sync_state
                SET to_update = 0
                WHERE to_update;
                """
            )

    def search_entries(
        self,
        query: str,
        filter_options: EntryFilterOptions = EntryFilterOptions(),  # noqa: B008
        chunk_size: Optional[int] = None,
        last: _SearchEntriesLast = None,
    ) -> Iterable[Tuple[EntrySearchResult, _SearchEntriesLast]]:

        rv = self._search_entries(
            query=query, filter_options=filter_options, chunk_size=chunk_size, last=last
        )

        # See comment in get_entries() for why we're doing this.
        if chunk_size:
            rv = iter(list(rv))

        return rv

    _query_error_message_fragments = [
        "fts5: syntax error near",
        "unknown special query",
        "no such column",
        "no such cursor",
        "unterminated string",
    ]

    def _search_entries(
        self,
        query: str,
        filter_options: EntryFilterOptions,
        chunk_size: Optional[int] = None,
        last: _SearchEntriesLast = None,
    ) -> Iterable[Tuple[EntrySearchResult, _SearchEntriesLast]]:
        sql_query = make_search_entries_query(filter_options, chunk_size, last)

        feed_url, entry_id, read, important, has_enclosures = filter_options

        # TODO: lots of get_entries duplication, should be reduced

        random_mark = ''.join(
            random.choices(string.ascii_letters + string.digits, k=20)
        )
        before_mark = f'>>>{random_mark}>>>'
        after_mark = f'<<<{random_mark}<<<'

        # 255 letters / 4.7 letters per word (average in English)
        snippet_tokens = 54

        clean_locals = dict(locals())
        clean_locals.pop('sql_query')
        log.debug("_search_entries locals\n%r\n", clean_locals)

        params = locals()
        params.update(sql_query.last_params(last))

        with wrap_exceptions(SearchError):
            try:
                cursor = self.storage.db.execute(str(sql_query), params)
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

            for t in cursor:
                (
                    rv_entry_id,
                    rv_feed_url,
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

                result = EntrySearchResult(
                    rv_feed_url,
                    rv_entry_id,
                    MappingProxyType(metadata),
                    MappingProxyType(rv_content),
                )

                rv_last = cast(_SearchEntriesLast, sql_query.extract_last(t))
                log.debug("_search_entries rv_last\n%r\n", rv_last)

                yield result, rv_last


def make_search_entries_query(
    filter_options: EntryFilterOptions,
    chunk_size: Optional[int] = None,
    last: _SearchEntriesLast = None,
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
        # TODO: can we improve performance if we move filtering here?
        # https://www.mail-archive.com/sqlite-users@mailinglists.sqlite.org/msg115821.html
        # rule 14 https://www.sqlite.org/optoverview.html#subquery_flattening
        .LIMIT("-1 OFFSET 0")
    )

    apply_filter_options(search, filter_options)

    query = (
        Query()
        .WITH(("search", search.__str__(end='')))
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
    if chunk_size:
        query.LIMIT(":chunk_size", last=last)

    log.debug("_search_entries query\n%s\n", query)

    return query
