from collections import namedtuple
import time
import datetime
import json
import logging
import re
import sqlite3

import feedparser

from .db import open_db


log = logging.getLogger(__name__)


Feed = namedtuple('Feed', 'url title link updated')

Entry = namedtuple('Entry', 'id title link updated published summary content enclosures read')


def _datetime_from_timetuple(tt):
    return datetime.datetime.fromtimestamp(time.mktime(tt)) if tt else None

def _get_updated_published(thing, is_rss):
    # feed.get and entry.get don't work for updated due historical reasons;
    # from the docs: "As of version 5.1.1, if this key [.updated] doesn't
    # exist but [thing].published does, the value of [thing].published
    # will be returned. [...] This mapping is temporary and will be
    # removed in a future version of feedparser."

    updated = None
    published = None
    if 'updated_parsed' in thing:
        updated = _datetime_from_timetuple(thing.updated_parsed)
    if 'published_parsed' in thing:
        published = _datetime_from_timetuple(thing.published_parsed)

    if published and not updated and is_rss:
            updated, published = published, None

    return updated, published


class Reader:

    def __init__(self, path=None, db=None):
        self.db = db if db else open_db(path)

    def add_feed(self, url):
        with self.db:
            self.db.execute("""
                INSERT INTO feeds (url)
                VALUES (:url);
            """, locals())

    def remove_feed(self, url):
        with self.db:
            self.db.execute("""
                DELETE FROM entry_tags
                WHERE feed = :url;
            """, locals())
            self.db.execute("""
                DELETE FROM entries
                WHERE feed = :url;
            """, locals())
            self.db.execute("""
                DELETE FROM feeds
                WHERE url = :url;
            """, locals())

    def update_feeds(self):
        cursor =  self.db.execute("""
            SELECT url, updated, http_etag, http_last_modified, stale FROM feeds
        """)
        for row in cursor:
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
        feed = feedparser.parse(url, etag=http_etag, modified=http_last_modified)

        if feed.bozo:
            log.warning("update feed %r: bozo feed, skipping; bozo exception: %r", url, feed.get('bozo_exception'))
            return

        if feed.get('status') == 304:
            log.info("update feed %r: got 304, skipping", url)
            return

        is_rss = feed.version.startswith('rss')
        updated, _ = _get_updated_published(feed.feed, is_rss)
        if not stale and updated and db_updated and updated <= db_updated:
            log.info("update feed %r: feed not updated, skipping", url)
            log.debug("update feed %r: old updated %s, new updated %s", url, db_updated, updated)
            return

        with self.db:
            title = feed.feed.get('title')
            link = feed.feed.get('link')
            http_etag = feed.get('etag')
            http_last_modified = feed.get('modified')

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
            for entry in feed.entries:
                entry_updated, entry_new = self._update_entry(url, entry, is_rss, stale)
                entries_updated += entry_updated
                entries_new += entry_new

            log.info("update feed %r: updated (updated %d, new %d)", url, entries_updated, entries_new)

    def _update_entry(self, feed_url, entry, is_rss, stale):
        assert self.db.in_transaction

        assert entry.id
        db_updated = self._get_entry_updated(feed_url, entry.id)
        updated, published = _get_updated_published(entry, is_rss)
        assert updated

        if stale:
            log.debug("update entry %r of feed %r: feed marked as stale, updating anyway", entry.id, feed_url)
        elif db_updated and updated <= db_updated:
            log.debug("update entry %r of feed %r: entry not updated, skipping (old updated %s, new updated %s)", entry.id, feed_url, db_updated, updated)
            return 0, 0

        id = entry.id
        title = entry.get('title')
        link = entry.get('link')
        summary = entry.get('summary')
        content = entry.get('content')
        content = json.dumps(content) if content else None
        enclosures = entry.get('enclosures')
        enclosures = json.dumps(enclosures) if enclosures else None

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

    def get_entries(self, _unread_only=False, _read_only=False):
        where_extra_snippet = ''
        assert _unread_only + _read_only <= 1
        if _unread_only:
            where_extra_snippet = """
                AND 'read' NOT IN tags_of_this_entry
            """
        elif _read_only:
            where_extra_snippet = """
                AND 'read' IN tags_of_this_entry
            """
        cursor = self.db.execute("""
            WITH tags_of_this_entry AS (
                SELECT tag
                FROM entry_tags
                WHERE entry_tags.entry = entries.id
                AND entry_tags.feed = entries.feed
            )
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
                entries.enclosures
            FROM entries, feeds
            WHERE feeds.url = entries.feed {}
            ORDER BY entries.updated DESC;
        """.format(where_extra_snippet))

        for t in cursor:
            feed = t[0:4]
            feed = Feed._make(feed)
            entry = t[4:10] + (
                json.loads(t[10]) if t[10] else None,
                json.loads(t[11]) if t[11] else None,
                'read' in self.get_entry_tags(t[0], t[4]),
            )
            entry = Entry._make(entry)
            yield feed, entry

    def add_entry_tag(self, feed_url, entry_id, tag):
        assert re.match('^[a-z0-9][a-z0-9-]+$', tag)
        with self.db:
            self.db.execute("""
                INSERT INTO entry_tags (
                    entry, feed, tag
                ) VALUES (
                    :entry_id, :feed_url, :tag
                );
            """, locals())

    def remove_entry_tag(self, feed_url, entry_id, tag):
        with self.db:
            self.db.execute("""
                DELETE FROM entry_tags
                WHERE entry = :entry_id
                    AND feed = :feed_url
                    AND tag = :tag;
            """, locals())

    def get_entry_tags(self, feed_url, entry_id):
        cursor = self.db.execute("""
            SELECT tag
            FROM entry_tags
            WHERE entry_tags.entry = :entry_id
            AND entry_tags.feed = :feed_url;
        """, locals())
        for t in cursor:
            yield t[0]

    def mark_as_read(self, feed_url, entry_id):
        try:
            self.add_entry_tag(feed_url, entry_id, 'read')
        except sqlite3.IntegrityError:
            pass

    def mark_as_unread(self, feed_url, entry_id):
        self.remove_entry_tag(feed_url, entry_id, 'read')

