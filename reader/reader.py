import json
import logging
import sqlite3
import functools
import contextlib

from .db import open_db
from .types import Feed, Entry
from .parser import parse
from .exceptions import (
    ParseError, NotModified,
    FeedExistsError, FeedNotFoundError, EntryNotFoundError,
    StorageError,
)

log = logging.getLogger('reader')


@contextlib.contextmanager
def wrap_storage_exceptions(*args):
    """Wrap sqlite3 exceptions in StorageError.

    Only wraps exceptions that are unlikely to be programming errors (bugs),
    can only be fixed by the user (e.g. access permission denied), and aren't
    domain-related (those should have other custom exceptions).

    This is an imprecise science, since the DB-API exceptions are somewhat
    fuzzy in their meaning and we can't access the SQLite result code.

    Full discussion at https://github.com/lemon24/reader/issues/21

    """

    try:
        yield
    except sqlite3.OperationalError as e:
        raise StorageError("sqlite3 error") from e



class Reader:

    _get_entries_chunk_size = 2 ** 8
    _parse = staticmethod(parse)

    @wrap_storage_exceptions()
    def __init__(self, path=None):
        self.db = open_db(path)

    @wrap_storage_exceptions()
    def add_feed(self, url):
        with self.db:
            try:
                self.db.execute("""
                    INSERT INTO feeds (url)
                    VALUES (:url);
                """, locals())
            except sqlite3.IntegrityError:
                raise FeedExistsError(url)

    @wrap_storage_exceptions()
    def remove_feed(self, url):
        with self.db:
            rows = self.db.execute("""
                DELETE FROM feeds
                WHERE url = :url;
            """, locals())
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    def _get_feeds(self, url=None):
        where_url_snippet = '' if not url else "WHERE url = :url"
        cursor = self.db.execute("""
            SELECT url, title, link, updated FROM feeds
            {where_url_snippet}
            ORDER BY feeds.title, feeds.url;
        """.format(**locals()), locals())

        for row in cursor:
            yield Feed._make(row)

    @wrap_storage_exceptions()
    def get_feeds(self):
        return list(self._get_feeds())

    @wrap_storage_exceptions()
    def get_feed(self, url):
        feeds = list(self._get_feeds(url))
        if len(feeds) == 0:
            return None
        elif len(feeds) == 1:
            return feeds[0]
        else:
            assert False, "shouldn't get here"  # pragma: no cover

    def _get_feeds_for_update(self, url=None):
        where_url_snippet = '' if not url else "WHERE url = :url"
        cursor = self.db.execute("""
            SELECT url, updated, http_etag, http_last_modified, stale FROM feeds
            {where_url_snippet}
            ORDER BY feeds.url;
        """.format(**locals()), locals())
        return cursor

    def _mark_as_stale(self, url):
        with self.db:
            rows = self.db.execute("""
                UPDATE feeds
                SET stale = 1
                WHERE url = :url;
            """, locals())
            if rows.rowcount == 0:
                raise FeedNotFoundError(url)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions()
    def update_feeds(self):
        for row in list(self._get_feeds_for_update()):
            try:
                self._update_feed(*row)
            except ParseError as e:
                log.warning("update feed %r: error while getting/parsing feed, skipping; exception: %r", e.url, e.__cause__)

    @wrap_storage_exceptions()
    def update_feed(self, url):
        rows = list(self._get_feeds_for_update(url))
        if len(rows) == 0:
            raise FeedNotFoundError(url)
        elif len(rows) == 1:
            self._update_feed(*rows[0])
        else:
            assert False, "shouldn't get here"  # pragma: no cover

    def _update_feed(self, url, db_updated, http_etag, http_last_modified, stale):
        if stale:
            db_updated = None
            http_etag = None
            http_last_modified = None
            log.info("update feed %r: feed marked as stale, ignoring updated, http_etag or http_last_modified", url)

        try:
            t = self._parse(url, http_etag, http_last_modified)
            feed, entries, http_etag, http_last_modified = t
        except NotModified:
            log.info("update feed %r: feed not modified, skipping", url)
            return

        updated = feed.updated
        if not stale and updated and db_updated and updated <= db_updated:
            log.info("update feed %r: feed not updated, skipping", url)
            log.debug("update feed %r: old updated %s, new updated %s", url, db_updated, updated)
            return

        title = feed.title
        link = feed.link

        with self.db:
            self.db.execute("""
                UPDATE feeds
                SET
                    title = :title,
                    link = :link,
                    updated = :updated,
                    http_etag = :http_etag,
                    http_last_modified = :http_last_modified,
                    stale = NULL
                WHERE url = :url;
            """, locals())

            entries_updated, entries_new = 0, 0
            for entry in entries:
                entry_updated, entry_new = self._update_entry(url, entry, stale)
                entries_updated += entry_updated
                entries_new += entry_new

            log.info("update feed %r: updated (updated %d, new %d)", url, entries_updated, entries_new)

    def _update_entry(self, feed_url, entry, stale):
        assert self.db.in_transaction

        db_updated = self._get_entry_updated(feed_url, entry.id)
        updated, published = entry.updated, entry.published

        if stale:
            log.debug("update entry %r of feed %r: feed marked as stale, updating anyway", entry.id, feed_url)
        elif db_updated and updated <= db_updated:
            log.debug("update entry %r of feed %r: entry not updated, skipping (old updated %s, new updated %s)", entry.id, feed_url, db_updated, updated)
            return 0, 0

        id = entry.id
        title = entry.title
        link = entry.link
        summary = entry.summary
        content = json.dumps(entry.content) if entry.content else None
        enclosures = json.dumps(entry.enclosures) if entry.enclosures else None

        if not db_updated:
            self.db.execute("""
                INSERT INTO entries (
                    id, feed, title, link, updated, published, summary, content, enclosures
                ) VALUES (
                    :id, :feed_url, :title, :link, :updated, :published, :summary, :content, :enclosures
                );
            """, locals())
            log.debug("update entry %r of feed %r: entry added", entry.id, feed_url)
            return 0, 1

        else:
            self.db.execute("""
                UPDATE entries
                SET
                    title = :title,
                    link = :link,
                    updated = :updated,
                    published = :published,
                    summary = :summary,
                    content = :content,
                    enclosures = :enclosures
                WHERE feed = :feed_url AND id = :id;
            """, locals())
            log.debug("update entry %r of feed %r: entry updated", entry.id, feed_url)
            return 1, 0

    def _get_entry_updated(self, feed_url, id):
        rv = self.db.execute("""
            SELECT updated
            FROM entries
            WHERE feed = :feed_url
                AND id = :id;
        """, locals()).fetchone()
        return rv[0] if rv else None

    def _get_entries(self, which, feed_url, chunk_size=None, last=None):
        log.debug("_get_entries chunk_size=%s last=%s", chunk_size, last)

        if which == 'all':
            where_read_snippet = ''
        elif which == 'unread':
            where_read_snippet = """
                AND (entries.read IS NULL OR entries.read != 1)
            """
        elif which == 'read':
            where_read_snippet = """
                AND entries.read = 1
            """
        else:
            assert False, "shouldn't get here"  # pragma: no cover

        where_next_snippet = ''
        limit_snippet = ''
        if chunk_size:
            limit_snippet = """
                LIMIT :chunk_size
            """
            if last:
                last_entry_updated, last_feed_url, last_entry_id = last
                where_next_snippet = """
                    AND (entries.updated, feeds.url, entries.id) <
                        (:last_entry_updated, :last_feed_url, :last_entry_id)
                """

        where_feed_snippet = ''
        if feed_url:
            where_feed_snippet = """
                AND feeds.url = :feed_url
            """

        query = """
            SELECT
                feeds.url,
                feeds.title,
                feeds.link,
                feeds.updated,
                entries.id,
                entries.title,
                entries.link,
                entries.updated,
                entries.published,
                entries.summary,
                entries.content,
                entries.enclosures,
                entries.read
            FROM entries, feeds
            WHERE
                feeds.url = entries.feed
                {where_read_snippet}
                {where_feed_snippet}
                {where_next_snippet}
            ORDER BY
                entries.updated DESC,
                feeds.url DESC,
                entries.id DESC
            {limit_snippet}
            ;
        """.format(**locals())

        log.debug("_get_entries query\n%s\n", query)
        with wrap_storage_exceptions():
            cursor = self.db.execute(query, locals())

        for t in cursor:
            feed = t[0:4]
            feed = Feed._make(feed)
            entry = t[4:10] + (
                json.loads(t[10]) if t[10] else None,
                json.loads(t[11]) if t[11] else None,
                t[12] == 1,
            )
            entry = Entry._make(entry)
            yield feed, entry

    @wrap_storage_exceptions()
    def get_entries(self, which='all', feed_url=None):
        if which not in ('all', 'unread', 'read'):
            raise ValueError("which should be one of ('all', 'read', 'unread')")
        chunk_size = self._get_entries_chunk_size

        last = None
        while True:

            entries = self._get_entries(
                which=which,
                feed_url=feed_url,
                chunk_size=chunk_size,
                last=last,
            )

            # When chunk_size is 0, don't chunk the query.
            #
            # This will ensure there are no missing/duplicated entries, but
            # will block database writes until the whole generator is consumed.
            #
            # Currently not exposed through the public API.
            #
            if not chunk_size:
                yield from entries
                return

            entries = list(entries)
            if not entries:
                break

            yield from entries

            last = (
                entries[-1][1].updated,
                entries[-1][0].url,
                entries[-1][1].id,
            )

    def _mark_as_read_unread(self, feed_url, entry_id, read):
        with self.db:
            rows = self.db.execute("""
                UPDATE entries
                SET read = :read
                WHERE feed = :feed_url AND id = :entry_id;
            """, locals())
            if rows.rowcount == 0:
                raise EntryNotFoundError(feed_url, entry_id)
            assert rows.rowcount == 1, "shouldn't have more than 1 row"

    @wrap_storage_exceptions()
    def mark_as_read(self, feed_url, entry_id):
       self._mark_as_read_unread(feed_url, entry_id, 1)

    @wrap_storage_exceptions()
    def mark_as_unread(self, feed_url, entry_id):
        self._mark_as_read_unread(feed_url, entry_id, 0)

