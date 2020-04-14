import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import Iterable
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import TYPE_CHECKING

from .types import EntryData
from .types import EntryForUpdate
from .types import EntryUpdateIntent
from .types import Feed
from .types import FeedForUpdate
from .types import FeedUpdateIntent
from .types import ParsedFeed
from .types import UpdatedEntry
from .types import UpdateResult

if TYPE_CHECKING:  # pragma: no cover
    from .storage import Storage


log = logging.getLogger("reader")


@dataclass
class Updater:

    old_feed: FeedForUpdate
    now: datetime
    global_now: datetime

    @classmethod
    def process_old_feed(cls, feed: FeedForUpdate) -> FeedForUpdate:
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

    def __post_init__(self) -> None:
        self.old_feed = self.process_old_feed(self.old_feed)

    @property
    def url(self) -> str:
        return self.old_feed.url

    @property
    def stale(self) -> bool:
        return self.old_feed.stale

    def should_update_feed(self, new: Feed) -> bool:
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
    ) -> Tuple[Optional[datetime], bool]:
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
            return None, False

        log_debug("entry added/updated")
        return (updated, True) if not old else (updated, False)

    def get_entry_pairs(
        self, entries: Iterable[EntryData[Optional[datetime]]], storage: "Storage"
    ) -> Iterable[Tuple[EntryData[Optional[datetime]], Optional[EntryForUpdate]]]:
        entries = list(entries)
        pairs = zip(
            entries,
            storage.get_entries_for_update([(e.feed_url, e.id) for e in entries]),
        )
        return pairs

    def get_entries_to_update(
        self,
        pairs: Iterable[Tuple[EntryData[Optional[datetime]], Optional[EntryForUpdate]]],
    ) -> Iterable[Tuple[EntryUpdateIntent, bool]]:
        last_updated = self.now
        for feed_order, (new_entry, old_entry) in reversed(list(enumerate(pairs))):

            # This may fail if we ever implement changing the feed URL
            # in response to a permanent redirect.
            assert (
                new_entry.feed_url == self.url
            ), f'{new_entry.feed_url!r}, {self.url!r}'

            updated, entry_new = self.should_update_entry(new_entry, old_entry)

            if updated:

                yield EntryUpdateIntent(
                    EntryData(**new_entry._replace(updated=updated).__dict__),
                    last_updated,
                    self.global_now if entry_new else None,
                    feed_order,
                ), entry_new

    def get_feed_to_update(
        self,
        parsed_feed: ParsedFeed,
        entries_to_update: Sequence[Tuple[EntryUpdateIntent, bool]],
    ) -> Optional[FeedUpdateIntent]:
        new_count = sum(bool(n) for _, n in entries_to_update)
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
        self, parsed_feed: Optional[ParsedFeed], storage: "Storage"
    ) -> UpdateResult:
        if not parsed_feed:
            log.info("update feed %r: feed not modified, skipping", self.url)
            # The feed shouldn't be considered new anymore.
            storage.update_feed(FeedUpdateIntent(self.url, self.now))
            return UpdateResult(())

        entries_to_update = list(
            self.get_entries_to_update(
                self.get_entry_pairs(parsed_feed.entries, storage)
            )
        )
        feed_to_update = self.get_feed_to_update(parsed_feed, entries_to_update)

        if entries_to_update:
            storage.add_or_update_entries(e for e, _ in entries_to_update)
        if feed_to_update:
            storage.update_feed(feed_to_update)

        # if self.url != parsed_feed.feed.url, the feed was redirected.
        # TODO: Maybe handle redirects somehow else (e.g. change URL if permanent).

        return UpdateResult((UpdatedEntry(e.entry, n) for e, n in entries_to_update))
