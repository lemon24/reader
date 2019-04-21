import logging
import datetime

import attr

from .exceptions import NotModified
from .types import FeedUpdateIntent, EntryUpdateIntent
from .types import UpdateResult, UpdatedEntry

log = logging.getLogger('reader')


@attr.s
class Updater:

    old_feed = attr.ib()
    now = attr.ib()
    global_now = attr.ib()

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
        old_updated = old.updated if old else None

        if self.stale:
            log.debug("update entry %r of feed %r: feed marked as stale, updating anyway", new.id, self.url)
        elif not new.updated:
            log.debug("update entry %r of feed %r: has no updated, updating but not changing updated", new.id, self.url)
            updated = old_updated or self.now
        elif old_updated and new.updated <= old_updated:
            log.debug("update entry %r of feed %r: entry not updated, skipping (old updated %s, new updated %s)", new.id, self.url, old_updated, new.updated)
            return None, False

        log.debug("update entry %r of feed %r: entry added/updated", new.id, self.url)
        return (updated, True) if not old else (updated, False)

    def get_entry_pairs(self, entries, storage):
        entries = list(entries)
        pairs = zip(entries, storage.get_entries_for_update([
            (self.url, e.id) for e in entries
        ]))
        return pairs

    def get_entries_to_update(self, pairs):
        last_updated = self.now
        for new_entry, old_entry in reversed(list(pairs)):
            assert new_entry.feed is None
            updated, entry_new = self.should_update_entry(new_entry, old_entry)

            if updated:
                yield EntryUpdateIntent(
                    self.url,
                    new_entry._replace(updated=updated),
                    last_updated,
                    self.global_now if entry_new else None,
                ), entry_new

            # TODO: Find a better way to preserve feed entry order.
            #
            # We increment last_updated so that new entries of a feed that
            # doesn't set updated on entries are ordered the same as they
            # were in the feed.
            #
            # This seems hacky in the same way first_updated does (see the
            # comment in Reader.udpate_feeds(). First, last_updated lies ever
            # so slightly. Second, both Storage and Updater need to know
            # about this.
            #
            # A solution would be to add another column / entry attribute,
            # feed_order. Is last_updated needed for anything else, then?
            #
            last_updated += datetime.timedelta(microseconds=1)

    def get_feed_to_update(self, parse_result, entries_to_update):
        new_count = sum(bool(n) for _, n in entries_to_update)
        updated_count = len(entries_to_update) - new_count

        log.info("update feed %r: updated (updated %d, new %d)",
            self.url, updated_count, new_count)

        if self.should_update_feed(parse_result.feed):
            feed_to_update = FeedUpdateIntent(
                self.url,
                parse_result.feed,
                parse_result.http_etag,
                parse_result.http_last_modified,
                self.now,
            )
        elif new_count or updated_count:
            feed_to_update = FeedUpdateIntent(self.url, None, None, None, self.now)
        else:
            feed_to_update = None

        return feed_to_update

    def update(self, parser, storage):
        try:
            parse_result = parser(self.url,
                                  self.old_feed.http_etag,
                                  self.old_feed.http_last_modified)
        except NotModified:
            log.info("update feed %r: feed not modified, skipping", self.url)
            # The feed shouldn't be considered new anymore.
            storage.update_feed(self.url, None, None, None, self.now)
            return UpdateResult(None, ())

        entries_to_update = list(self.get_entries_to_update(
            self.get_entry_pairs(parse_result.entries, storage)))
        feed_to_update = self.get_feed_to_update(parse_result, entries_to_update)

        if entries_to_update:
            storage.add_or_update_entries(e for e, _ in entries_to_update)
        if feed_to_update:
            storage.update_feed(*feed_to_update)

        return UpdateResult(
            parse_result.feed.url if parse_result.feed else None,
            (UpdatedEntry(e.entry, n) for e, n in entries_to_update),
        )


