import feedparser

from collections import namedtuple
import time
import datetime
import json


Feed = namedtuple('Feed', 'url title link updated')

Entry = namedtuple('Entry', 'id title link updated published enclosures')


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

    def __init__(self, db):
        self.db = db

    def add_feed(self, url):
        with self.db:
            self.db.execute("""
                INSERT INTO feeds (url)
                VALUES (:url);
            """, locals())

    def update_feeds(self):
        cursor =  self.db.execute("""
            SELECT url, updated, http_etag, http_last_modified FROM feeds
        """)
        for row in cursor:
            self._update_feed(*row)

    def _update_feed(self, url, db_updated, http_etag, http_last_modified):
        feed = feedparser.parse(url, etag=http_etag, modified=http_last_modified)

        if feed.get('status') == 304:
            return

        is_rss = feed.version.startswith('rss')
        updated, _ = _get_updated_published(feed.feed, is_rss)
        if updated and db_updated and updated <= db_updated:
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
                    http_last_modified = :http_last_modified
                WHERE url = :url;
            """, locals())

            for entry in feed.entries:
                self._update_entry(url, entry, is_rss)

    def _update_entry(self, feed_url, entry, is_rss):
        assert self.db.in_transaction

        assert entry.id
        db_updated = self._get_entry_updated(feed_url, entry.id)
        updated, published = _get_updated_published(entry, is_rss)
        assert updated
        if db_updated and updated <= db_updated:
            return

        id = entry.id
        title = entry.get('title')
        link = entry.get('link')
        enclosures = entry.get('enclosures')
        enclosures = json.dumps(enclosures) if enclosures else None

        if not db_updated:
            self.db.execute("""
                INSERT INTO entries (
                    id, feed, title, link, updated, published, enclosures
                ) VALUES (
                    :id, :feed_url, :title, :link, :updated, :published, :enclosures
                );
            """, locals())

        else:
            self.db.execute("""
                UPDATE entries
                SET
                    title = :title,
                    link = :link,
                    updated = :updated,
                    published = :published,
                    enclosures = :enclosures
                WHERE feed = :feed_url AND id = :id;
            """, locals())

    def _get_entry_updated(self, feed_url, id):
        rv = self.db.execute("""
            SELECT updated
            FROM entries
            WHERE feed = :feed_url
                AND id = :id;
        """, locals()).fetchone()
        return rv[0] if rv else None

    def get_entries(self):
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
                entries.enclosures
            FROM entries, feeds
            WHERE feeds.url = entries.feed
            ORDER BY entries.updated DESC;
        """)

        for t in cursor:
            feed = t[0:4]
            feed = Feed._make(feed)
            entry = t[4:9] + (json.loads(t[9]) if t[9] else None, )
            entry = Entry._make(entry)
            yield feed, entry

