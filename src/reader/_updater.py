import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import cast
from typing import Iterable
from typing import Optional
from typing import Tuple
from typing import Union

from ._types import EntryData
from ._types import EntryForUpdate
from ._types import EntryUpdateIntent
from ._types import FeedData
from ._types import FeedForUpdate
from ._types import FeedUpdateIntent
from ._types import ParsedFeed
from ._utils import PrefixLogger
from .exceptions import ParseError
from .types import ExceptionInfo

log = logging.getLogger("reader")

HASH_CHANGED_LIMIT = 24


def process_old_feed(feed: FeedForUpdate) -> FeedForUpdate:
    if feed.stale:
        # db_updated=None not tested (removing it causes no tests to fail).
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
    parsed_feed: Union[ParsedFeed, ParseError],
    entry_pairs: Iterable[
        Tuple[EntryData[Optional[datetime]], Optional[EntryForUpdate]]
    ],
) -> Tuple[Optional[FeedUpdateIntent], Iterable[EntryUpdateIntent]]:
    updater = _Updater(
        old_feed,
        now,
        global_now,
        PrefixLogger(log, ["update feed %r" % old_feed.url]),
    )
    return updater.update(parsed_feed, entry_pairs)


@dataclass(frozen=True)
class _Updater:

    """This is an object only to make logging easier."""

    old_feed: FeedForUpdate
    now: datetime
    global_now: datetime
    log: Union[logging.Logger, logging.LoggerAdapter] = log

    def __post_init__(self) -> None:
        object.__setattr__(self, 'old_feed', process_old_feed(self.old_feed))

    @property
    def url(self) -> str:
        return self.old_feed.url

    @property
    def stale(self) -> bool:
        return self.old_feed.stale

    def should_update_feed(self, new: FeedData, entries_to_update: bool) -> bool:
        old = self.old_feed
        self.log.debug("old updated %s, new updated %s", old.updated, new.updated)

        if not old.last_updated:
            self.log.info("feed has no last_updated, treating as updated")
            assert not old.updated, "updated must be None if last_updated is None"
            return True

        if not new.updated:
            self.log.info("feed has no updated, treating as updated")
            return True

        if self.stale:
            # logging for stale happened in process_old_feed()
            return True

        # we only care if feed.updated changed if any entries changed:
        # https://github.com/lemon24/reader/issues/231#issuecomment-812601988
        #
        # for RSS, if there's no date element,
        # feedparser user lastBuildDate as .updated,
        # which may (obviously) change without the feed actually changing
        #
        if entries_to_update and (not old.updated or new.updated > old.updated):
            self.log.info("feed updated")
            return True

        # check if the feed content actually changed:
        # https://github.com/lemon24/reader/issues/179
        if not old.hash or new.hash != old.hash:
            self.log.debug("feed hash changed, treating as updated")
            return True

        # Some feeds have entries newer than the feed.
        # https://github.com/lemon24/reader/issues/76
        self.log.info("feed not updated, updating entries anyway")

        return False

    def compute_entry_updated(
        self, id: str, new: Optional[datetime], old: Optional[datetime]
    ) -> Optional[datetime]:
        def debug(msg: str, *args: Any) -> None:
            self.log.debug("entry %r: " + msg, id, *args)

        if not new:
            debug("has no updated, updating but not changing updated")
            debug("entry added/updated")
            return old or self.now

        if self.stale:
            debug("feed marked as stale, updating anyway")
            debug("entry added/updated")
            return new

        if old and new <= old:
            debug(
                "entry not updated, skipping (old updated %s, new updated %s)", old, new
            )
            return None

        debug("entry updated")
        return new

    def should_update_entry(
        self, new: EntryData[Optional[datetime]], old: Optional[EntryForUpdate]
    ) -> Tuple[Optional[EntryData[datetime]], bool]:

        updated = self.compute_entry_updated(new.id, new.updated, old and old.updated)

        if updated:
            return EntryData(**new._replace(updated=updated).__dict__), False

        # At this point, new should have .updated is not None.
        # otherwise, compute_entry_updated() would have returned
        # either old.updated or self.now.
        # Remove this when it stops doing that, as proposed in this comment:
        # https://github.com/lemon24/reader/issues/179#issuecomment-663840297
        assert new.updated is not None

        # If old is None, compute_entry_updated() returned something.
        assert old is not None

        # Check if the entry content actually changed:
        # https://github.com/lemon24/reader/issues/179
        #
        # We limit the number of updates due to only the hash changing
        # to prevent spurious updates for entries whose content changes
        # excessively (for example, because it includes the current time).
        # https://github.com/lemon24/reader/issues/225
        #
        if not old.hash or new.hash != old.hash:
            if (old.hash_changed or 0) < HASH_CHANGED_LIMIT:
                self.log.debug("entry %r: entry hash changed, updating", new.id)
                # mypy does not automatically "cast" new to EntryData[datetime]
                return cast(EntryData[datetime], new), True
            else:
                self.log.debug(
                    "entry %r: entry hash changed, "
                    "but exceeds the update limit (%i); skipping",
                    new.id,
                    HASH_CHANGED_LIMIT,
                )

        return None, False

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

            entry_new = not old_entry
            processed_new_entry, due_to_hash_changed = self.should_update_entry(
                new_entry, old_entry
            )

            if processed_new_entry:
                yield EntryUpdateIntent(
                    processed_new_entry,
                    last_updated,
                    self.global_now if entry_new else None,
                    feed_order,
                    0
                    if not due_to_hash_changed
                    else ((old_entry and old_entry.hash_changed or 0) + 1),
                )

    def get_feed_to_update(
        self,
        parsed_feed: ParsedFeed,
        entries_to_update: bool,
    ) -> Optional[FeedUpdateIntent]:
        if self.should_update_feed(parsed_feed.feed, entries_to_update):
            return FeedUpdateIntent(
                self.url,
                self.now,
                parsed_feed.feed,
                parsed_feed.http_etag,
                parsed_feed.http_last_modified,
            )
        if entries_to_update:
            return FeedUpdateIntent(self.url, self.now)
        return None

    def update(
        self,
        parsed_feed: Union[ParsedFeed, None, ParseError],
        entry_pairs: Iterable[
            Tuple[EntryData[Optional[datetime]], Optional[EntryForUpdate]]
        ],
    ) -> Tuple[Optional[FeedUpdateIntent], Iterable[EntryUpdateIntent]]:

        # Not modified.
        if not parsed_feed:

            # New feed shouldn't be considered new anymore.
            if not self.old_feed.last_updated:
                return FeedUpdateIntent(self.url, self.now), ()

            # Clear last_exception.
            if self.old_feed.last_exception:
                return FeedUpdateIntent(self.url, self.old_feed.last_updated), ()

            return None, ()

        if isinstance(parsed_feed, ParseError):
            exc_info = ExceptionInfo.from_exception(
                parsed_feed.__cause__ or parsed_feed
            )
            return FeedUpdateIntent(self.url, None, last_exception=exc_info), ()

        entries_to_update = list(self.get_entries_to_update(entry_pairs))
        feed_to_update = self.get_feed_to_update(parsed_feed, bool(entries_to_update))

        if not feed_to_update and self.old_feed.last_exception:
            # Clear last_exception.
            # TODO: Maybe be more explicit about this? (i.e. have a storage method for it)
            feed_to_update = FeedUpdateIntent(self.url, self.old_feed.last_updated)

        return feed_to_update, entries_to_update
