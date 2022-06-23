from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from itertools import chain
from itertools import starmap
from itertools import tee
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Optional
from typing import Tuple
from typing import TYPE_CHECKING
from typing import Union

from ._types import EntryData
from ._types import EntryForUpdate
from ._types import EntryUpdateIntent
from ._types import FeedData
from ._types import FeedForUpdate
from ._types import FeedUpdateIntent
from ._types import ParsedFeed
from ._utils import PrefixLogger
from .exceptions import FeedNotFoundError
from .exceptions import ParseError
from .types import EntryUpdateStatus
from .types import ExceptionInfo
from .types import UpdatedFeed
from .types import UpdateResult

if TYPE_CHECKING:  # pragma: no cover
    from ._parser import Parser
    from ._storage import Storage
    from ._types import EntryUpdateIntent
    from ._types import FeedFilterOptions
    from ._types import FeedUpdateIntent
    from ._utils import MapType
    from .core import Reader


log = logging.getLogger("reader")

HASH_CHANGED_LIMIT = 24


EntryPairs = Iterable[Tuple[EntryData, Optional[EntryForUpdate]]]


@dataclass(frozen=True)
class Decider:

    """Decide whether a feed or entry should be updated.

    Does not interact with any dependencies, only processes data.

    This is an object only to make logging easier.

    """

    old_feed: FeedForUpdate
    now: datetime
    global_now: datetime
    log: Any = log

    @classmethod
    def process_feed_for_update(cls, feed: FeedForUpdate) -> FeedForUpdate:
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

    @classmethod
    def make_intents(
        cls,
        old_feed: FeedForUpdate,
        now: datetime,
        global_now: datetime,
        parsed_feed: Union[ParsedFeed, None, ParseError],
        entry_pairs: EntryPairs,
    ) -> Tuple[Optional[FeedUpdateIntent], Iterable[EntryUpdateIntent]]:
        decider = cls(
            old_feed,
            now,
            global_now,
            PrefixLogger(log, ["update feed %r" % old_feed.url]),
        )
        return decider.update(parsed_feed, entry_pairs)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, 'old_feed', self.process_feed_for_update(self.old_feed)
        )

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
            # logging for stale happened in process_feed_for_update()
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

    def should_update_entry(
        self, new: EntryData, old: Optional[EntryForUpdate]
    ) -> Tuple[Optional[EntryData], bool]:
        def debug(msg: str, *args: Any) -> None:
            self.log.debug("entry %r: " + msg, new.id, *args)

        if self.stale:
            debug("feed marked as stale, updating")
            return new, False

        if not old:
            debug("entry new, updating")
            return new, False

        new_updated = new.updated or new.published
        old_updated = old.updated or old.published

        if not new_updated:
            debug("entry has no updated, updating")
            return new, False

        if not (old_updated and new_updated <= old_updated):
            debug("entry updated, updating")
            return new, False

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
                debug("entry hash changed, updating")
                return new, True
            else:
                debug(
                    "entry hash changed, but exceeds the update limit (%i); skipping",
                    HASH_CHANGED_LIMIT,
                )
                return None, False

        debug(
            "entry not updated, skipping (old updated %s, new updated %s)",
            old_updated,
            new_updated,
        )

        return None, False

    def get_entries_to_update(self, pairs: EntryPairs) -> Iterable[EntryUpdateIntent]:
        for feed_order, (new, old) in reversed(list(enumerate(pairs))):

            # This may fail if we ever implement changing the feed URL
            # in response to a permanent redirect.
            assert new.feed_url == self.url, f'{new.feed_url!r}, {self.url!r}'

            is_new = not old
            processed_new, due_to_hash_changed = self.should_update_entry(new, old)

            if processed_new:
                if due_to_hash_changed:
                    hash_changed = (old and old.hash_changed or 0) + 1
                else:
                    hash_changed = 0

                yield EntryUpdateIntent(
                    processed_new,
                    self.now,
                    self.now if is_new else None,
                    self.global_now if is_new else None,
                    feed_order,
                    hash_changed,
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
        entry_pairs: EntryPairs,
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


@dataclass(frozen=True)
class Pipeline:

    """Update multiple feeds.

    Calls dependencies and hooks in the right order, possibly in parallel.

    Does not decide whether a feed or entry *should* be updated.

    Logical pipeline (pseudocode)::

        storage.get_feeds_for_update
        | xargs -n1 parser.process_feed_for_update
        | xargs -n1 decider.process_feed_for_update
        | xargs -n1 -P $workers parser.retrieve
        | xargs -n1 parser.parse
        | xargs -n1 storage.get_entries_for_update
        | xargs -n1 parser.process_entry_pairs
        | xargs -n1 decider.make_intents
        | xargs -n1 update_feed

    At the moment, only parser.retrieve runs in parallel.

    """

    storage: Storage
    parser: Parser
    now: Callable[[], datetime]
    map: MapType
    # for hooks' usage *only*
    reader: Reader
    decider = Decider

    @classmethod
    def from_reader(cls, reader: Reader, map: MapType) -> 'Pipeline':
        return cls(
            storage=reader._storage,
            parser=reader._parser,
            now=reader._now,
            map=map,
            reader=reader,
        )

    def update(self, filter_options: FeedFilterOptions) -> Iterable[UpdateResult]:

        # global_now is used as first_updated_epoch for all new entries,
        # so that the subset of new entries from an update appears before
        # all others and the entries in it are sorted by published/updated;
        # if we used last_updated (now) for this, they would be sorted
        # by feed order first (due to now increasing for each feed).
        #
        # A side effect of relying first_updated_epoch for ordering is that
        # for the second of two new feeds updated in the same update_feeds()
        # call, first_updated_epoch != last_updated.
        #
        # However, added == last_updated for the first update.
        #
        global_now = self.now()

        is_parallel = self.map is not map
        process_parse_result = partial(self.process_parse_result, global_now)

        # ಠ_ಠ
        # The pipeline is not equipped to handle ParseErrors
        # as early as parser.process_feed_for_update().
        # So, we stash them away and don't retrieve/parse those feeds,
        # and then tack them on at the end of parse_results.
        # Storing the exceptions until the end of the generator
        # might cause memory issues, but the caller may need to raise them.
        # TODO: Rework update pipeline to support process_feed_for_update() exceptions.
        parser_process_feeds_for_update_errors = []

        def parser_process_feeds_for_update(
            feeds: Iterable[FeedForUpdate],
        ) -> Iterable[FeedForUpdate]:
            for feed in feeds:
                try:
                    yield self.parser.process_feed_for_update(feed)
                except ParseError as e:
                    parser_process_feeds_for_update_errors.append((feed, e))

        # assemble pipeline
        feeds_for_update = self.storage.get_feeds_for_update(filter_options)
        # feeds_for_update = map(self.parser.process_feed_for_update, feeds_for_update)
        feeds_for_update = parser_process_feeds_for_update(feeds_for_update)
        feeds_for_update = map(self.decider.process_feed_for_update, feeds_for_update)
        parse_results = self.parser.parallel(feeds_for_update, self.map, is_parallel)
        parse_results = chain(parse_results, parser_process_feeds_for_update_errors)
        update_results = starmap(process_parse_result, parse_results)

        for url, value in update_results:
            if isinstance(value, FeedNotFoundError):
                log.info("update feed %r: feed removed during update", url)
                continue

            if isinstance(value, Exception):
                if not isinstance(value, ParseError):
                    raise value

            yield UpdateResult(url, value)

    def process_parse_result(
        self,
        global_now: datetime,
        feed: FeedForUpdate,
        result: Union[Optional[ParsedFeed], ParseError],
    ) -> Tuple[str, Union[UpdatedFeed, None, Exception]]:

        make_intents = partial(
            self.decider.make_intents, feed, self.now(), global_now, result
        )

        try:
            # assemble pipeline
            entry_pairs = self.get_entry_pairs(result)
            if result and not isinstance(result, Exception):
                entry_pairs = self.parser.process_entry_pairs(
                    feed.url, result.mime_type, entry_pairs
                )
            intents = make_intents(entry_pairs)
            counts = self.update_feed(feed.url, *intents)

        except Exception as e:
            return feed.url, e

        if not result or isinstance(result, Exception):
            return feed.url, result

        return feed.url, UpdatedFeed(feed.url, *counts)

    def get_entry_pairs(
        self, result: Union[Optional[ParsedFeed], ParseError]
    ) -> EntryPairs:
        if not result or isinstance(result, Exception):
            return ()

        # give storage a chance to consume entries in a streaming fashion
        entries1, entries2 = tee(result.entries)
        entries_for_update = self.storage.get_entries_for_update(
            (e.feed_url, e.id) for e in entries1
        )
        return zip(entries2, entries_for_update)

    def update_feed(
        self,
        url: str,
        feed: Optional[FeedUpdateIntent],
        entries: Iterable[EntryUpdateIntent],
    ) -> Tuple[int, int]:

        for feed_hook in self.reader.before_feed_update_hooks:
            feed_hook(self.reader, url)

        if feed:
            if entries:
                self.storage.add_or_update_entries(entries)
            self.storage.update_feed(feed)

        # if feed_for_update.url != parsed_feed.feed.url, the feed was redirected.
        # TODO: Maybe handle redirects somehow else (e.g. change URL if permanent).

        new_count = 0
        updated_count = 0
        for entry in entries:
            if entry.new:
                new_count += 1
                entry_status = EntryUpdateStatus.NEW
            else:
                updated_count += 1
                entry_status = EntryUpdateStatus.MODIFIED
            for entry_hook in self.reader.after_entry_update_hooks:
                entry_hook(self.reader, entry.entry, entry_status)

        for feed_hook in self.reader.after_feed_update_hooks:
            feed_hook(self.reader, url)

        return new_count, updated_count
