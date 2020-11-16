import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import Iterable
from typing import Optional
from typing import Sequence
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
from .exceptions import _NotModified
from .exceptions import ParseError
from .types import ExceptionInfo

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
    parsed_feed: Union[ParsedFeed, ParseError, _NotModified],
    entry_pairs: Iterable[
        Tuple[EntryData[Optional[datetime]], Optional[EntryForUpdate]]
    ],
) -> Tuple[
    Optional[FeedUpdateIntent], Iterable[EntryUpdateIntent], Optional[ParseError]
]:
    updater = _Updater(
        old_feed, now, global_now, PrefixLogger(log, ["update feed %r" % old_feed.url]),
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

    def should_update_feed(self, new: FeedData) -> bool:
        old = self.old_feed
        self.log.debug("old updated %s, new updated %s", old.updated, new.updated)

        if not old.last_updated:
            self.log.info("feed has no last_updated, treating as updated")
            feed_was_updated = True

            assert not old.updated, "updated must be None if last_updated is None"

        elif not new.updated:
            self.log.info("feed has no updated, treating as updated")
            feed_was_updated = True
        else:
            feed_was_updated = not (
                new.updated and old.updated and new.updated <= old.updated
            )

        should_be_updated = self.stale or feed_was_updated

        if not should_be_updated:
            # Some feeds have entries newer than the feed.
            # https://github.com/lemon24/reader/issues/76
            self.log.info("feed not updated, updating entries anyway")

        return should_be_updated

    def should_update_entry(
        self, new: EntryData[Optional[datetime]], old: Optional[EntryForUpdate]
    ) -> Optional[datetime]:
        def debug(msg: str, *args: Any) -> None:
            self.log.debug("entry %r: " + msg, new.id, *args)

        updated = new.updated
        old_updated = old.updated if old else None

        if self.stale:
            debug("feed marked as stale, updating anyway")
        elif not new.updated:
            debug("has no updated, updating but not changing updated")
            updated = old_updated or self.now
        elif old_updated and new.updated <= old_updated:
            debug(
                "entry not updated, skipping (old updated %s, new updated %s)",
                old_updated,
                new.updated,
            )
            return None

        debug("entry added/updated")
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

        self.log.info("updated (updated %d, new %d)", updated_count, new_count)

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
        parsed_feed: Union[ParsedFeed, ParseError, _NotModified],
        entry_pairs: Iterable[
            Tuple[EntryData[Optional[datetime]], Optional[EntryForUpdate]]
        ],
    ) -> Tuple[
        Optional[FeedUpdateIntent], Iterable[EntryUpdateIntent], Optional[ParseError]
    ]:
        if isinstance(parsed_feed, Exception):
            if isinstance(parsed_feed, _NotModified):
                self.log.info("feed not modified, skipping")
                # The feed shouldn't be considered new anymore.
                if not self.old_feed.last_updated:
                    return FeedUpdateIntent(self.url, self.now), (), None
                # Clear last_exception.
                if self.old_feed.last_exception:
                    return (
                        FeedUpdateIntent(self.url, self.old_feed.last_updated),
                        (),
                        None,
                    )
                return None, (), None

            if isinstance(parsed_feed, ParseError):
                exc_info = ExceptionInfo.from_exception(
                    parsed_feed.__cause__ or parsed_feed
                )
                return (
                    FeedUpdateIntent(self.url, None, last_exception=exc_info),
                    (),
                    parsed_feed,
                )

            assert False, "shouldn't happen"  # noqa: B011; # pragma: no cover

        entries_to_update = list(self.get_entries_to_update(entry_pairs))
        feed_to_update = self.get_feed_to_update(parsed_feed, entries_to_update)

        if not feed_to_update and self.old_feed.last_exception:
            # Clear last_exception.
            # TODO: Maybe be more explicit about this? (i.e. have a storage method for it)
            feed_to_update = FeedUpdateIntent(self.url, self.old_feed.last_updated)

        return feed_to_update, entries_to_update, None
