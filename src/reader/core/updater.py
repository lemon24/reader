import logging
import datetime

import attr

from .exceptions import NotModified

log = logging.getLogger('reader')


def update_feed(old_feed, now, global_now, parser, storage):
    updater = Updater(old_feed, now, global_now)
    updater.update(parser, storage)
    return updater.new_feed, updater.new_entries


@attr.s
class Updater:

    old_feed = attr.ib()
    now = attr.ib()
    global_now = attr.ib()

    new_feed = attr.ib(default=None)
    new_entries = attr.ib(default=attr.Factory(list))
    updated_entries = attr.ib(default=attr.Factory(list))

    def __attrs_post_init__(self):
        if self.old_feed.stale:
            # db_updated=None not ot tested (removing it causes no tests to fail).
            #
            # This only matters if last_updated is None *and* db_updated is
            # not None. The way the code is, this shouldn't be possible
            # (last_updated is always set if the feed was updated at least
            # once, unless the database predates last_updated).
            #
            self.old_feed = self.old_feed._replace(updated=None, http_etag=None, http_last_modified=None)
            log.info("update feed %r: feed marked as stale, ignoring updated, http_etag and http_last_modified", self.url)

    @property
    def url(self):
        return self.old_feed.url

    @property
    def stale(self):
        return self.old_feed.stale

    def should_update_feed(self, new):
        old = self.old_feed
        log.debug("update feed %r: old updated %s, new updated %s", self.url, old.updated, new.updated)

        if not old.last_updated:
            log.info("update feed %r: feed has no last_updated, treating as updated", self.url)
            feed_was_updated = True

            assert not old.updated, "updated must be None if last_updated is None"

        elif not new.updated:
            log.info("update feed %r: feed has no updated, treating as updated", self.url)
            feed_was_updated = True
        else:
            feed_was_updated = not(new.updated
                                   and old.updated
                                   and new.updated <= old.updated)

        should_be_updated = self.stale or feed_was_updated

        if not should_be_updated:
            # Some feeds have entries newer than the feed.
            # https://github.com/lemon24/reader/issues/76
            log.info("update feed %r: feed not updated, updating entries anyway", self.url)

        return should_be_updated

    def should_update_entry(self, new, old):
        updated = new.updated

        if self.stale:
            log.debug("update entry %r of feed %r: feed marked as stale, updating anyway", new.id, self.url)
        elif not new.updated:
            log.debug("update entry %r of feed %r: has no updated, updating but not changing updated", new.id, self.url)
            updated = old.updated or self.now
        elif old.updated and new.updated <= old.updated:
            log.debug("update entry %r of feed %r: entry not updated, skipping (old updated %s, new updated %s)", new.id, self.url, old.updated, new.updated)
            return 0, 0, updated

        log.debug("update entry %r of feed %r: entry added/updated", new.id, self.url)
        return (0, 1, updated) if not old.exists else (1, 0, updated)

    def get_entries_to_update(self, entries, storage):
        entries = list(entries)
        pairs = zip(entries, storage.get_entries_for_update([
            (self.url, e.id) for e in entries
        ]))

        last_updated = self.now
        for new_entry, old_entry in reversed(list(pairs)):
            assert new_entry.feed is None
            entry_updated, entry_new, updated = self.should_update_entry(new_entry, old_entry)

            if entry_updated or entry_new:
                yield entry_new, new_entry, updated, last_updated

            last_updated += datetime.timedelta(microseconds=1)

    def prepare_entries_for_update(self, entries_to_update):
        self.updated_entries = []
        self.new_entries = []

        for entry_new, entry, updated, last_updated in entries_to_update:
            if entry_new:
                self.new_entries.append(entry)
            else:
                self.updated_entries.append(entry)
            yield (
                self.url,
                entry,
                updated,
                last_updated,
                self.global_now if entry_new else None,
            )

    def update(self, parser, storage):
        try:
            parse_result = parser(self.url,
                                  self.old_feed.http_etag,
                                  self.old_feed.http_last_modified)
        except NotModified:
            log.info("update feed %r: feed not modified, skipping", self.url)
            # The feed shouldn't be considered new anymore.
            storage.update_feed_last_updated(self.url, self.now)
            return None, ()

        self.new_feed = parse_result.feed

        should_update_feed = self.should_update_feed(parse_result.feed)

        entries_to_update = self.get_entries_to_update(parse_result.entries, storage)
        entries_for_update = self.prepare_entries_for_update(entries_to_update)
        storage.add_or_update_entries(entries_for_update)

        if should_update_feed:
            storage.update_feed(self.url,
                                parse_result.feed,
                                parse_result.http_etag,
                                parse_result.http_last_modified,
                                self.now)
        elif self.new_entries or self.updated_entries:
            storage.update_feed_last_updated(self.url, self.now)

        log.info("update feed %r: updated (updated %d, new %d)",
                 self.url, len(self.updated_entries), len(self.new_entries))

