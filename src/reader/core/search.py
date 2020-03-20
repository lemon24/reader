import functools
import json
import logging
import sqlite3
import warnings
from typing import Any
from typing import Iterable
from typing import Optional
from typing import Tuple
from typing import TypeVar

try:
    import bs4  # type: ignore
except ImportError:  # pragma: no cover
    bs4 = None

from .exceptions import InvalidSearchQueryError
from .exceptions import SearchError
from .exceptions import SearchNotEnabledError

from .sqlite_utils import ddl_transaction
from .types import EntrySearchResult, EntryFilterOptions
from .storage import Storage, wrap_storage_exceptions


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
        with ddl_transaction(self.storage.db) as db:

            # The column names matter, as they can be used in column filters;
            # https://www.sqlite.org/fts5.html#fts5_column_filters
            db.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS entries_search USING fts5(
                    _id UNINDEXED,
                    _feed UNINDEXED,
                    _content_path UNINDEXED,
                    title,  -- entries.title
                    text,  -- entries.summary or one of entries.content; FIXME: better name?
                    feed,  -- feeds.title
                    tokenize = "porter unicode61 remove_diacritics 1 tokenchars '_'"
                );
                """
            )
            # FIXME: we still need to tune the rank weights, these are just guesses
            db.execute(
                """
                INSERT INTO entries_search(entries_search, rank)
                VALUES ('rank', 'bm25(1, 1, 1, 4, 1, 2)');
                """
            )

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS entries_search_sync_state (
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

            # TODO: use "UPDATE OF ... ON" instead (needs tests)
            # TODO: only run UPDATE triggers if the values are actually different (needs tests)
            # TODO: what happens if the feed ID changes? can't happen yet; also see https://github.com/lemon24/reader/issues/149

            db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS entries_search_entries_insert
                AFTER INSERT ON entries
                BEGIN
                    INSERT INTO entries_search_sync_state
                    VALUES (new.id, new.feed, 1, 0);
                END;
                """
            )
            db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS entries_search_entries_update
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
                CREATE TRIGGER IF NOT EXISTS entries_search_entries_delete
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
                CREATE TRIGGER IF NOT EXISTS entries_search_feeds_update
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
        # TODO: similar to HeavyMigration.get_version(); pull into table_exists()
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
        # FIXME: do we search through all content types?
        # FIXME: should raise some kind of custom exception if bs4 is not available,
        # otherwise we get only SearchError: sqlite3 error: user-defined function raised exception (alternatively, check on exception, and warn on other methods)

        self.storage.db.create_function('strip_html', 1, strip_html)

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
                        'summary',
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
                        'content.' || json_each.key,
                        strip_html(entries.title),
                        strip_html(json_extract(json_each.value, '$.value'))
                    FROM entries_search_sync_state
                    JOIN entries USING (id, feed)
                    JOIN json_each(entries.content)
                    WHERE
                        entries_search_sync_state.to_update
                        AND json_valid(content) and json_array_length(content) > 0
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
                    union_all.id,
                    union_all.feed as feed,
                    union_all.content_path,
                    union_all.title,
                    union_all.content_text,
                    strip_html(coalesce(feeds.user_title, feeds.title))
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

    _SearchEntriesLast = Optional[Tuple[Any, Any, Any]]

    def search_entries(
        self,
        query: str,
        filter_options: EntryFilterOptions = EntryFilterOptions(),
        *,
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
        filter_options: EntryFilterOptions = EntryFilterOptions(),
        *,
        chunk_size: Optional[int] = None,
        last: _SearchEntriesLast = None,
    ) -> Iterable[Tuple[EntrySearchResult, _SearchEntriesLast]]:
        sql_query = self._make_search_entries_query(filter_options, chunk_size, last)

        feed_url, entry_id, read, important, has_enclosures = filter_options

        # TODO: lots of get_entries duplication, should be reduced

        if last:
            last = last_rank, last_feed_url, last_entry_id = last

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
                rv_entry_id, rv_feed_url, rv_rank, rv_title, *_ = t

                result = EntrySearchResult(rv_entry_id, rv_feed_url, rv_title)

                yield result, (rv_rank, rv_feed_url, rv_entry_id)

    def _make_search_entries_query(
        self,
        filter_options: EntryFilterOptions = EntryFilterOptions(),
        chunk_size: Optional[int] = None,
        last: _SearchEntriesLast = None,
    ) -> str:
        # TODO: should not duplicate _make_get_entries_query

        feed_url, entry_id, read, important, has_enclosures = filter_options

        where_snippets = []

        if read is not None:
            where_snippets.append(f"{'' if read else 'NOT'} entries.read")

        limit_snippet = ''
        if chunk_size:
            limit_snippet = """
                LIMIT :chunk_size
                """
            if last:
                where_snippets.append(
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
            where_snippets.append("entries.feed = :feed_url")
            if entry_id:
                where_snippets.append("entries.id = :entry_id")

        if has_enclosures is not None:
            where_snippets.append(
                f"""
                {'NOT' if has_enclosures else ''}
                    (json_array_length(entries.enclosures) IS NULL
                        OR json_array_length(entries.enclosures) = 0)
            """
            )

        if important is not None:
            where_snippets.append(f"{'' if important else 'NOT'} entries.important")

        if any(where_snippets):
            where_keyword = 'WHERE'
            where_snippet = '\n                AND '.join(where_snippets)
        else:
            where_keyword = ''
            where_snippet = ''

        query = f"""

            WITH search AS (
                SELECT
                    _id,
                    _feed,
                    rank,
                    highlight(entries_search, 3, '>>>', '<<<') as title,
                    highlight(entries_search, 5, '>>>', '<<<') as feed,
                    json_object(
                        'content_path', _content_path,
                        'rank', rank,
                        'text', snippet(entries_search, 4, '>>>', '<<<', '...', 12)
                    ) as text
                FROM entries_search
                WHERE entries_search MATCH :query

                -- https://www.mail-archive.com/sqlite-users@mailinglists.sqlite.org/msg115821.html
                -- rule 14 of https://www.sqlite.org/optoverview.html#subquery_flattening
                LIMIT -1 OFFSET 0
            )

            SELECT
                entries.id,
                entries.feed,
                min(search.rank) as rank,
                search.title,
                search.feed,
                json_group_array(json(search.text)) as text
            FROM entries
            JOIN search ON (entries.id, entries.feed) = (search._id, search._feed)
            {where_keyword}
                {where_snippet}
            GROUP BY entries.id, entries.feed
            ORDER BY rank, entries.id, entries.feed
            {limit_snippet}
            ;

        """

        log.debug("_search_entries query\n%s\n", query)

        return query
