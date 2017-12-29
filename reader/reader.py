import feedparser

from collections import namedtuple
import time
import datetime
import json


def _datetime_from_timetuple(tt):
    return datetime.datetime.fromtimestamp(time.mktime(tt)) if tt else None


Feed = namedtuple('Feed', 'url title link updated')

Entry = namedtuple('Entry', 'id title link updated published enclosures')


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
            SELECT url, etag, modified_original FROM feeds
        """)
        for url, etag, modified_original in cursor:
            self._update_feed(url, etag, modified_original)

    def _update_feed(self, url, etag, modified_original):
        feed = feedparser.parse(url, etag=etag, modified=modified_original)

        if feed.get('status') == 304:
            return

        # TODO: also check feed.updated

        with self.db:
            title = feed.feed.get('title')
            link = feed.feed.get('link')
            etag = feed.get('etag')
            modified_original = feed.get('modified')

            self.db.execute("""
                UPDATE feeds
                SET
                    title = :title,
                    link = :link,
                    etag = :etag,
                    modified_original = :modified_original
                WHERE url = :url;
            """, locals())

            for entry in feed.entries:
                self._update_entry(url, entry)

    def _update_entry(self, url, entry):
        assert self.db.in_transaction

        assert entry.id
        db_updated = self._get_entry_updated(url, entry.id)
        updated = _datetime_from_timetuple(entry.get('updated_parsed'))
        assert updated

        enclosures = entry.get('enclosures')

        params = {
            'id': entry.id,
            'feed': url,
            'title': entry.get('title'),
            'link': entry.get('link'),
            'updated': updated,
            'published': _datetime_from_timetuple(entry.get('published_parsed')),
            'enclosures': json.dumps(enclosures) if enclosures else None,
        }

        if not db_updated:
            self.db.execute("""
                INSERT INTO entries (
                    id, feed, title, link, updated, published, enclosures
                ) VALUES (
                    :id, :feed, :title, :link, :updated, :published, :enclosures
                );
            """, params)

        elif updated > db_updated:
            self.db.execute("""
                UPDATE entries
                SET
                    title = :title,
                    link = :link,
                    updated = :updated,
                    published = :published,
                    enclosures = :enclosures
                WHERE feed = :feed AND id = :id;
            """, params)

    def _get_entry_updated(self, url, id):
        rv = self.db.execute("""
            SELECT updated
            FROM entries
            WHERE feed = :url
                AND id = :id;
        """, locals()).fetchone()
        return rv[0] if rv else None

    def get_entries(self):
        cursor = self.db.execute("""
            SELECT
                feeds.url,
                feeds.title,
                feeds.link,
                entries.id,
                entries.title,
                entries.link,
                entries.updated,
                entries.published,
                entries.enclosures
            FROM entries, feeds
            WHERE feeds.url = entries.feed
            ORDER BY entries.published DESC, entries.updated DESC;
        """)

        for t in cursor:
            feed = t[0:3] + (None, )
            feed = Feed._make(feed)
            entry = t[3:8] + (json.loads(t[8]) if t[8] else None, )
            entry = Entry._make(entry)
            yield feed, entry

