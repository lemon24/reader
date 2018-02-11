import json
import logging

from .db import open_db
from .types import Feed, Entry
from .parser import parse, ParseError, NotModified


log = logging.getLogger(__name__)


class Reader:

    _get_entries_chunk_size = 2 ** 8
    _parse = staticmethod(parse)

    def __init__(self, path=None):
        self.db = open_db(path)

    def add_feed(self, url):
        with self.db:
            self.db.execute("""
                INSERT INTO feeds (url)
                VALUES (:url);
            """, locals())

    def remove_feed(self, url):
        with self.db:
            self.db.execute("""
                DELETE FROM feeds
                WHERE url = :url;
            """, locals())

    def get_feeds(self):
        cursor = self.db.execute("""
            SELECT url, title, link, updated FROM feeds
        """)
        for row in list(cursor):
            yield Feed._make(row)

    def get_feed(self, url):
        cursor = self.db.execute("""
            SELECT url, title, link, updated FROM feeds
            WHERE url = :url
        """, locals())
        rows = list(cursor)
        if len(rows) == 0:
            return None
        elif len(rows) == 1:
            return Feed._make(rows[0])
        else:
            assert False, "shouldn't get here"

    def update_feeds(self):
        cursor =  self.db.execute("""
            SELECT url, updated, http_etag, http_last_modified, stale FROM feeds
        """)
        for row in list(cursor):
            self._update_feed(*row)

    def update_feed(self, url):
        cursor =  self.db.execute("""
            SELECT url, updated, http_etag, http_last_modified, stale FROM feeds
            WHERE url = :url
        """, locals())
        rows = list(cursor)
        if len(rows) == 0:
            log.warning("update feed %r: unknown feed", url)
        elif len(rows) == 1:
            self._update_feed(*rows[0])
        else:
            assert False, "shouldn't get here"

    def _update_feed(self, url, db_updated, http_etag, http_last_modified, stale):
        if stale:
            db_updated = None
            http_etag = None
            http_last_modified = None
            log.info("update feed %r: feed marked as stale, ignoring updated, http_etag or http_last_modified", url)

        try:
            t = self._parse(url, http_etag, http_last_modified)
            feed, entries, http_etag, http_last_modified = t
        except ParseError as e:
            log.warning("update feed %r: error while getting/parsing feed, skipping; exception: %r", url, e.exception)
            return
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
            assert False, "shouldn't get here"

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

        cursor = self.db.execute("""
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
        """.format(**locals()), locals())

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

    def mark_as_read(self, feed_url, entry_id):
        with self.db:
            self.db.execute("""
                UPDATE entries
                SET read = 1
                WHERE feed = :feed_url AND id = :entry_id;
            """, locals())

    def mark_as_unread(self, feed_url, entry_id):
        with self.db:
            self.db.execute("""
                UPDATE entries
                SET read = 0
                WHERE feed = :feed_url AND id = :entry_id;
            """, locals())

