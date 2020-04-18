import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import Iterable
from typing import Optional
from typing import Sequence
from typing import Tuple

from ._types import EntryData
from ._types import EntryForUpdate
from ._types import EntryUpdateIntent
from ._types import FeedData
from ._types import FeedForUpdate
from ._types import FeedUpdateIntent
from ._types import ParsedFeed


log = logging.getLogger("reader")


def process_old_feed(feed: FeedForUpdate) -> FeedForUpdate:
    if feed.stale:
        # db_updated=None not ot tested (removing it causes no tests to fail).
        #
        # This only matters if last_updated is None *and* db_updated is
        # not None. The way the code is, this shouldn't be possible
        # (last_updated is always set if the feed was updated at least
        # once, unless the database predates last_updated).
        #
        feed = feed._replace(updated=None, http_etag=None, http_last_modified=None)
        log.info(
            "update feed %r: feed marked as stale, "
            "ignoring updated, http_etag and http_last_modified",
            feed.url,
        )
    return feed


def make_update_intents(
    old_feed: FeedForUpdate,
    now: datetime,
    global_now: datetime,
    parsed_feed: Optional[ParsedFeed],
    entry_pairs: Iterable[
        Tuple[EntryData[Optional[datetime]], Optional[EntryForUpdate]]
    ],
) -> Tuple[Optional[FeedUpdateIntent], Iterable[EntryUpdateIntent]]:
    updater = _Updater(old_feed, now, global_now)
    return updater.update(parsed_feed, entry_pairs)


@dataclass
class _Updater:

    """This is an object only to make logging easier."""

    old_feed: FeedForUpdate
    now: datetime
    global_now: datetime

    def __post_init__(self) -> None:
        self.old_feed = process_old_feed(self.old_feed)

    @property
    def url(self) -> str:
        return self.old_feed.url

    @property
    def stale(self) -> bool:
        return self.old_feed.stale

    def should_update_feed(self, new: FeedData) -> bool:
        def log_info(msg: str, *args: Any) -> None:
            log.info("update feed %r: " + msg, self.url, *args)

        old = self.old_feed
        log.debug(
            "update feed %r: old updated %s, new updated %s",
            self.url,
            old.updated,
            new.updated,
        )

        if not old.last_updated:
            log_info("feed has no last_updated, treating as updated")
            feed_was_updated = True

            assert not old.updated, "updated must be None if last_updated is None"

        elif not new.updated:
            log_info("feed has no updated, treating as updated")
            feed_was_updated = True
        else:
            feed_was_updated = not (
                new.updated and old.updated and new.updated <= old.updated
            )

        should_be_updated = self.stale or feed_was_updated

        if not should_be_updated:
            # Some feeds have entries newer than the feed.
            # https://github.com/lemon24/reader/issues/76
            log_info("feed not updated, updating entries anyway")

        return should_be_updated

    def should_update_entry(
        self, new: EntryData[Optional[datetime]], old: Optional[EntryForUpdate]
    ) -> Optional[datetime]:
        def log_debug(msg: str, *args: Any) -> None:
            log.debug("update entry %r of feed %r: " + msg, new.id, self.url, *args)

        updated = new.updated
        old_updated = old.updated if old else None

        if self.stale:
            log_debug("feed marked as stale, updating anyway")
        elif not new.updated:
            log_debug("has no updated, updating but not changing updated")
            updated = old_updated or self.now
        elif old_updated and new.updated <= old_updated:
            log_debug(
                "entry not updated, skipping (old updated %s, new updated %s)",
                old_updated,
                new.updated,
            )
            return None

        log_debug("entry added/updated")
        return updated

    def get_entries_to_update(
        self,
        pairs: Iterable[Tuple[EntryData[Optional[datetime]], Optional[EntryForUpdate]]],
    ) -> Iterable[EntryUpdateIntent]:
        last_updated = self.now
        for feed_order, (new_entry, old_entry) in reversed(list(enumerate(pairs))):

            # This may fail if we ever implement changing the feed URL
            # in response to a permanent redirect.
            assert (
                new_entry.feed_url == self.url
            ), f'{new_entry.feed_url!r}, {self.url!r}'

            updated = self.should_update_entry(new_entry, old_entry)
            entry_new = not old_entry

            if updated:

                yield EntryUpdateIntent(
                    EntryData(**new_entry._replace(updated=updated).__dict__),
                    last_updated,
                    self.global_now if entry_new else None,
                    feed_order,
                )

    def get_feed_to_update(
        self, parsed_feed: ParsedFeed, entries_to_update: Sequence[EntryUpdateIntent],
    ) -> Optional[FeedUpdateIntent]:
        new_count = sum(e.new for e in entries_to_update)
        updated_count = len(entries_to_update) - new_count

        log.info(
            "update feed %r: updated (updated %d, new %d)",
            self.url,
            updated_count,
            new_count,
        )

        feed_to_update: Optional[FeedUpdateIntent]
        if self.should_update_feed(parsed_feed.feed):
            feed_to_update = FeedUpdateIntent(
                self.url,
                self.now,
                parsed_feed.feed,
                parsed_feed.http_etag,
                parsed_feed.http_last_modified,
            )
        elif new_count or updated_count:
            feed_to_update = FeedUpdateIntent(self.url, self.now)
        else:
            feed_to_update = None

        return feed_to_update

    def update(
        self,
        parsed_feed: Optional[ParsedFeed],
        entry_pairs: Iterable[
            Tuple[EntryData[Optional[datetime]], Optional[EntryForUpdate]]
        ],
    ) -> Tuple[Optional[FeedUpdateIntent], Iterable[EntryUpdateIntent]]:
        if not parsed_feed:
            log.info("update feed %r: feed not modified, skipping", self.url)
            # The feed shouldn't be considered new anymore.
            return FeedUpdateIntent(self.url, self.now), ()

        entries_to_update = list(self.get_entries_to_update(entry_pairs))
        feed_to_update = self.get_feed_to_update(parsed_feed, entries_to_update)

        return feed_to_update, entries_to_update
