import logging
import datetime

from .exceptions import NotModified

log = logging.getLogger('reader')


def update_feed(feed_for_update, now, parser, storage):
    url = feed_for_update.url
    stale = feed_for_update.stale

    if stale:
        http_etag = None
        http_last_modified = None
        log.info("update feed %r: feed marked as stale, ignoring http_etag and http_last_modified", url)
    else:
        http_etag = feed_for_update.http_etag
        http_last_modified = feed_for_update.http_last_modified

    try:
        parsed_feed = parser(url, http_etag, http_last_modified)
    except NotModified:
        log.info("update feed %r: feed not modified, skipping", url)
        # The feed shouldn't be considered new anymore.
        storage.update_feed_last_updated(url, now)
        return None, ()

    parsed_feed = parsed_feed._replace(entries=(
        (e, storage.get_entry_for_update(url, e.id))
        for e in parsed_feed.entries
    ))

    should_update_feed, entries_to_update = update_feed_inner(now, feed_for_update, parsed_feed)

    updated_count = 0
    new_count = 0
    new_entries = []

    def prepare_entries_for_update():
        nonlocal updated_count, new_count
        for entry_new, entry, updated, last_updated in entries_to_update:
            if entry_new:
                new_count += 1
                new_entries.append(entry)
            else:
                updated_count += 1
            yield url, entry, updated, last_updated

    storage.add_or_update_entries(prepare_entries_for_update())

    if should_update_feed:
        storage.update_feed(url, parsed_feed.feed, parsed_feed.http_etag,
                            parsed_feed.http_last_modified, now)
    elif new_count or updated_count:
        storage.update_feed_last_updated(url, now)

    log.info("update feed %r: updated (updated %d, new %d)", url, updated_count, new_count)

    return parsed_feed.feed, new_entries


def update_feed_inner(now, feed_for_update, parsed_feed):
    url, db_updated, _, _, stale, last_updated = feed_for_update
    feed, entries, http_etag, http_last_modified = parsed_feed

    if stale:
        # Not tested (replaced the line with pass and no tests failed).
        #
        # This only matters if last_updated is None *and* db_updated is
        # not None. The way the code is, this shouldn't be possible
        # (last_updated is always set if the feed was updated at least
        # once, unless the database predates last_updated). Added an
        # assert in the "if not last_updated" block for this.
        #
        db_updated = None
        log.info("update feed %r: feed marked as stale, ignoring updated", url)

    updated = feed.updated
    log.debug("update feed %r: old updated %s, new updated %s", url, db_updated, updated)

    if not last_updated:
        log.info("update feed %r: feed has no last_updated, treating as updated", url)
        feed_was_updated = True

        assert not db_updated, "updated must be None if last_updated is None"

    elif not updated:
        log.info("update feed %r: feed has no updated, treating as updated", url)
        feed_was_updated = True
    else:
        feed_was_updated = not(updated and db_updated and updated <= db_updated)

    should_be_updated = stale or feed_was_updated

    if not should_be_updated:
        # Some feeds have entries newer than the feed.
        # https://github.com/lemon24/reader/issues/76
        log.info("update feed %r: feed not updated, updating entries anyway", url)

    def filter_entries_for_update():
        last_updated = now
        for entry, entry_for_update in reversed(list(entries)):
            assert entry.feed is None
            entry_updated, entry_new, updated = should_update_entry(url, entry, stale, now, entry_for_update)

            if entry_updated or entry_new:
                yield entry_new, entry, updated, last_updated

            last_updated += datetime.timedelta(microseconds=1)

    return should_be_updated, filter_entries_for_update()


def should_update_entry(feed_url, entry, stale, now, entry_for_update):
    entry_exists, db_updated = entry_for_update
    updated = entry.updated

    if stale:
        log.debug("update entry %r of feed %r: feed marked as stale, updating anyway", entry.id, feed_url)
    elif not updated:
        log.debug("update entry %r of feed %r: has no updated, updating but not changing updated", entry.id, feed_url)
        updated = db_updated or now
    elif db_updated and updated <= db_updated:
        log.debug("update entry %r of feed %r: entry not updated, skipping (old updated %s, new updated %s)", entry.id, feed_url, db_updated, updated)
        return 0, 0, updated

    log.debug("update entry %r of feed %r: entry added/updated", entry.id, feed_url)
    return (0, 1, updated) if not entry_exists else (1, 0, updated)

