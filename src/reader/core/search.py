import functools
import json
import logging
import random
import re
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

# Only Search.update() has a reason to fail if bs4 is missing.
try:
    import bs4  # type: ignore

    bs4_import_error = None
except ImportError as e:  # pragma: no cover
    bs4 = None
    bs4_import_error = e

from .exceptions import InvalidSearchQueryError
from .exceptions import SearchError
from .exceptions import SearchNotEnabledError

from .sqlite_utils import ddl_transaction
from .types import EntrySearchResult, EntryFilterOptions, HighlightedString
from .storage import Storage, wrap_storage_exceptions, DEFAULT_FILTER_OPTIONS


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
    'ignore', message='No parser was explicitly specified', module='reader.core.search'
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

    # TODO: Remove this assert once bs4 gets type annotations.
    rv = soup.get_text(separator='\n')
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

    @wrap_storage_exceptions(SearchError)
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

    @wrap_storage_exceptions(SearchError)
    def disable(self) -> None:
        with ddl_transaction(self.storage.db) as db:
            db.execute("DROP TABLE IF EXISTS entries_search;")
            db.execute("DROP TABLE IF EXISTS entries_search_sync_state;")
            db.execute("DROP TRIGGER IF EXISTS entries_search_entries_insert;")
            db.execute("DROP TRIGGER IF EXISTS entries_search_entries_update;")
            db.execute("DROP TRIGGER IF EXISTS entries_search_entries_delete;")
            db.execute("DROP TRIGGER IF EXISTS entries_search_feeds_update;")

    @wrap_storage_exceptions(SearchError)
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

    @wrap_storage_exceptions(SearchError)
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
        filter_options: EntryFilterOptions = DEFAULT_FILTER_OPTIONS,
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
        sql_query = self._make_search_entries_query(filter_options, chunk_size, last)

        feed_url, entry_id, read, important, has_enclosures = filter_options

        # TODO: lots of get_entries duplication, should be reduced

        if last:
            last = last_rank, last_feed_url, last_entry_id = last

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

        with wrap_storage_exceptions(SearchError):
            try:
                cursor = self.storage.db.execute(sql_query, locals())
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
                    metadata['.title'] = extract_highlights(
                        title, before_mark, after_mark
                    )
                if feed_title:
                    metadata[
                        '.feed.title' if not is_feed_user_title else '.feed.user_title'
                    ] = extract_highlights(feed_title, before_mark, after_mark)

                rv_content: Dict[str, HighlightedString] = OrderedDict(
                    (c['path'], extract_highlights(c['value'], before_mark, after_mark))
                    for c in content
                    if c['path']
                )

                result = EntrySearchResult(
                    rv_entry_id,
                    rv_feed_url,
                    MappingProxyType(metadata),
                    MappingProxyType(rv_content),
                )

                rv_last = (rank, rv_feed_url, rv_entry_id)
                log.debug("_search_entries rv_last\n%r\n", rv_last)

                yield result, rv_last

    def _make_search_entries_query(
        self,
        filter_options: EntryFilterOptions,
        chunk_size: Optional[int] = None,
        last: _SearchEntriesLast = None,
    ) -> str:
        # TODO: should not duplicate _make_get_entries_query

        feed_url, entry_id, read, important, has_enclosures = filter_options

        having_snippets = []

        if read is not None:
            having_snippets.append(f"{'' if read else 'NOT'} entries.read")

        limit_snippet = ''
        if chunk_size:
            limit_snippet = "LIMIT :chunk_size"
            if last:
                having_snippets.append(
                    """
                    (
                        rank,
                        entries.feed,
                        entries.id
                    ) > (
                        :last_rank,
                        :last_feed_url,
                        :last_entry_id
                    )
                    """
                )

        if feed_url:
            having_snippets.append("entries.feed = :feed_url")
            if entry_id:
                having_snippets.append("entries.id = :entry_id")

        if has_enclosures is not None:
            having_snippets.append(
                f"""
                {'NOT' if has_enclosures else ''}
                    (json_array_length(entries.enclosures) IS NULL
                        OR json_array_length(entries.enclosures) = 0)
                """
            )

        if important is not None:
            having_snippets.append(f"{'' if important else 'NOT'} entries.important")

        if any(having_snippets):
            having_keyword = 'HAVING'
            having_snippet = '\n                AND '.join(having_snippets)
        else:
            having_keyword = ''
            having_snippet = ''

        query = f"""

            WITH search AS (
                SELECT
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
                        )
                    ) AS content
                FROM entries_search
                WHERE entries_search MATCH :query
                ORDER BY rank

                -- https://www.mail-archive.com/sqlite-users@mailinglists.sqlite.org/msg115821.html
                -- rule 14 https://www.sqlite.org/optoverview.html#subquery_flattening
                LIMIT -1 OFFSET 0
            )

            SELECT
                entries.id,
                entries.feed,
                min(search.rank) as rank,  -- used for pagination
                search.title,
                search.feed,
                search.is_feed_user_title,
                json_group_array(json(search.content))
            FROM entries
            JOIN search ON (entries.id, entries.feed) = (search._id, search._feed)

            GROUP BY entries.id, entries.feed
            {having_keyword}
                {having_snippet}
            ORDER BY rank, entries.id, entries.feed
            {limit_snippet}
            ;

        """

        log.debug("_search_entries query\n%s\n", query)

        return query


def extract_highlights(text: str, before: str, after: str) -> HighlightedString:
    """
    >>> extract_highlights( '>one< two >three< four', '>', '<')
    HighlightedString(value='one two three four', highlights=[slice(0, 3, None), slice(8, 13, None)])

    """
    pattern = f"({'|'.join(re.escape(s) for s in (before, after))})"

    parts = []
    slices = []

    index = 0
    start = None

    for part in re.split(pattern, text):
        if part == before:
            if start is not None:
                raise ValueError("highlight start marker in highlight")
            start = index
            continue

        if part == after:
            if start is None:
                raise ValueError("unmatched highlight end marker")
            slices.append(slice(start, index))
            start = None
            continue

        parts.append(part)
        index += len(part)

    if start is not None:
        raise ValueError("highlight is never closed")

    return HighlightedString(''.join(parts), tuple(slices))


def json_object_get(object_str: str, key: str) -> Any:
    """Extract a key from a string containing a JSON object.

    >>> json_object_get('{"k": "v"}', 'k')
    'v'

    Because of a bug in SQLite[1][2], json_extract fails for strings
    containing non-BMP characters (e.g. some emojis).

    However, when the result of json_extract is passed to a user-defined
    function, instead of failing, the function silently gets passed NULL:

    % cat bug.py
    import sqlite3, json
    db = sqlite3.connect(":memory:")
    db.create_function("udf", 1, lambda x: x)
    json_string = json.dumps("🤩")
    print(*db.execute("select udf(json_extract(?, '$'));", (json_string,)))
    print(*db.execute("select json_extract(?, '$');", (json_string,)))
    % python bug.py
    (None,)
    Traceback (most recent call last):
      File "bug.py", line 6, in <module>
        print(*db.execute("select json_extract(?, '$');", (json_string,)))
    sqlite3.OperationalError: Could not decode to UTF-8 column 'json_extract(?, '$')' with text '������'

    To work around this, we define json_object_get(value, key), equivalent
    to json_extract(value, '$.' || key), which covers our use case.

    [1]: https://www.mail-archive.com/sqlite-users@mailinglists.sqlite.org/msg117549.html
    [2]: https://bugs.python.org/issue38749

    """
    return json.loads(object_str)[key]
