from __future__ import annotations

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from itertools import chain
from typing import Any
from typing import NamedTuple

from .._logging import get_logger
from .._parser import EntryPair
from .._parser import EntryPairBase
from .._parser import ParsedFeed
from .._parser import ParseResult
from .._types import EntryData
from .._types import EntryForUpdate
from .._types import EntryUpdateIntent
from .._types import FeedData
from .._types import FeedForUpdate
from .._types import FeedToUpdate
from .._types import FeedUpdateIntent
from .._types import UpdateInfo
from .._utils import make_pool_map
from ..exceptions import ParseError
from ..types import ExceptionInfo
from ..types import UpdateConfig
from ..types import UpdatedFeed
from .base import make_updated_feed
from .base import PipelineBase

logger = get_logger('reader.update')


HASH_CHANGED_LIMIT = 24
UPDATE_HISTORY_LIMIT = 8


EntryUpdateIntentPair = EntryPairBase[EntryUpdateIntent]


@dataclass(frozen=True)
class Decider:
    """Decide whether a feed or entry should be updated.

    Does not interact with any dependencies, only processes data.

    This is an object only to make logging easier.

    """

    old_feed: FeedForUpdate
    now: datetime

    # global now, is used as first_updated_epoch for all new entries,
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
    global_now: datetime
    config: UpdateConfig

    @classmethod
    def process_feed_for_update(cls, feed: FeedForUpdate) -> FeedForUpdate:
        if feed.stale:
            feed = feed._replace(caching_info=None)
            logger.info("stale feed, ignoring caching_info", feed=feed.url)
        return feed

    @classmethod
    def make_intents(
        cls,
        now: datetime,
        global_now: datetime,
        config: UpdateConfig,
        result: ParseResult,
        entry_pairs: Iterable[EntryPair],
    ) -> tuple[FeedUpdateIntent, Iterable[EntryUpdateIntentPair]]:
        decider = cls(
            result.feed,
            now,
            global_now,
            config,
        )
        return decider.update(result, entry_pairs)

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

        if self.stale:
            # logging for stale happened in process_feed_for_update()
            return True

        if not old.last_updated:
            logger.debug("feed has no last_updated, treating as updated")
            return True

        # Some feeds have entries newer than the feed;
        # we always update the feed if entries changed, for simplicity.
        # https://github.com/lemon24/reader/issues/76
        if entries_to_update:
            logger.debug("feed has entries to update, treating as updated")
            return True

        # Check if the feed content actually changed:
        # https://github.com/lemon24/reader/issues/179
        if not old.hash or new.hash != old.hash:
            logger.debug("feed hash changed, treating as updated")
            return True

        logger.debug("feed not updated, skipping")
        return False

    def should_update_entry(
        self, new: EntryData, old: EntryForUpdate | None
    ) -> UpdateReasons | None:
        log = logger.bind(entry=new.id)

        if self.stale:
            log.debug("feed marked as stale, updating")
            return UpdateReasons()

        if not old:
            log.debug("entry new, updating")
            return UpdateReasons()

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
                log.debug("entry hash changed, updating")
                return UpdateReasons((old.hash_changed or 0) + 1)
            else:
                log.debug(
                    "entry hash changed, but exceeds the update limit (%i); skipping",
                    HASH_CHANGED_LIMIT,
                )
                return None

        log.debug("entry not updated, skipping")
        return None

    def get_entries_to_update(
        self, pairs: Iterable[EntryPair]
    ) -> Iterable[EntryUpdateIntentPair]:
        for feed_order, (new, old) in reversed(list(enumerate(pairs))):
            # This may fail if we ever implement changing the feed URL
            # in response to a permanent redirect.
            assert new.feed_url == self.url, f'{new.feed_url!r}, {self.url!r}'

            should_update = self.should_update_entry(new, old)
            if not should_update:
                continue

            if not old:
                if not self.old_feed.last_updated:
                    # WARNING: keep in sync _update and add_entry
                    recent_sort = new.published or new.updated or self.global_now
                else:
                    recent_sort = self.global_now
            else:
                recent_sort = old.recent_sort

            yield EntryUpdateIntent(
                new,
                self.now,
                self.now if not old else old.first_updated,
                self.global_now if not old else old.first_updated_epoch,
                recent_sort,
                feed_order,
                should_update.hash_changed,
            ), old

    def get_feed_to_update(
        self, parsed_feed: ParsedFeed, entries_to_update: bool
    ) -> FeedToUpdate | None:
        if self.should_update_feed(parsed_feed.feed, entries_to_update):
            return FeedToUpdate(parsed_feed.feed, self.now, parsed_feed.caching_info)
        return None

    def update(
        self, result: ParseResult, entry_pairs: Iterable[EntryPair]
    ) -> tuple[FeedUpdateIntent, Iterable[EntryUpdateIntentPair]]:

        entries_to_update: list[EntryUpdateIntentPair] = []
        value: FeedToUpdate | None | ExceptionInfo
        info_result: UpdatedFeed | None | ExceptionInfo

        if not result.value:
            value = info_result = None
        elif isinstance(result.value, ParseError):
            value = ExceptionInfo.from_exception(result.value)
            info_result = value._replace(traceback_str='')
        else:
            entries_to_update = list(self.get_entries_to_update(entry_pairs))
            value = self.get_feed_to_update(result.value, bool(entries_to_update))
            info_result = make_updated_feed(result, entries_to_update)

        update_after_hints = []
        if hint := (result.metadata and result.metadata.update_after):
            if isinstance(hint, timedelta):
                hint = self.now + hint
            hint = min(hint, self.now + MAX_UPDATE_AFTER_HINT)
            update_after_hints.append(hint)

        elif isinstance(result.value, ParseError):
            old = self.old_feed
            if old.last_retrieved and old.update_after:
                hint = self.now + (old.update_after - old.last_retrieved) * 2
                hint = min(hint, self.now + MAX_UPDATE_AFTER_ERROR)
                update_after_hints.append(hint)

        else:
            # In absence of explicit expiration times, RFC 9111 recommends
            # an expiration time of 10% since last modification time;
            # one hour per day is ~4%, slightly faster.
            # https://httpwg.org/specs/rfc9111.html#heuristic.freshness
            if last_updated := self.old_feed.last_updated:
                hint = self.now + timedelta(hours=(self.now - last_updated).days)
                hint = min(hint, self.now + MAX_UPDATE_AFTER_HEURISTIC)
                update_after_hints.append(hint)

        update_after = next_update_after(self.now, *update_after_hints, **self.config)

        update_info = UpdateInfo(
            self.old_feed.url, info_result, self.now, result.metadata
        )
        update_history = self.old_feed.update_history + [update_info]
        update_history = update_history[-UPDATE_HISTORY_LIMIT:]

        # We always return a FeedUpdateIntent because
        # we always want to set last_retrieved and update_after,
        # and clear last_exception (if set before the update).

        return (
            FeedUpdateIntent(self.url, self.now, update_after, update_history, value),
            entries_to_update,
        )


class UpdateReasons(NamedTuple):
    hash_changed: int = 0


DEFAULT_CONFIG = UpdateConfig(interval=60, jitter=0)
CONFIG_KEY = 'update'


def flatten_config(config: Any, default: UpdateConfig) -> UpdateConfig:
    rv = default.copy()

    if not isinstance(config, dict):
        logger.warning(
            "invalid update config, expected dict, got %s", type(config).__name__
        )
        return rv

    set_number('interval', config, rv, int, min=1)  # type: ignore
    set_number('jitter', config, rv, float, max=1)  # type: ignore
    return rv


def set_number(name, src, dst, type, min=0, max=float('inf')):  # type: ignore
    try:
        value = src[name]
    except KeyError:
        return

    try:
        value = type(value)
    except (TypeError, ValueError) as e:
        logger.warning("invalid update config .%s: %s", name, e)
        return

    if not (min <= value <= max):
        logger.warning(
            "invalid update config .%s: must be between %s and %s: %s",
            name,
            min,
            max,
            value,
        )
        return

    dst[name] = value


UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
UPDATE_AFTER_EPOCH = datetime(1970, 1, 5, tzinfo=timezone.utc)
MAX_UPDATE_AFTER_HINT = timedelta(28)
MAX_UPDATE_AFTER_ERROR = timedelta(7)
MAX_UPDATE_AFTER_HEURISTIC = timedelta(1)


def next_update_after(
    now: datetime, *hints: datetime, interval: int, jitter: float = 0
) -> datetime:
    interval_s = interval * 60

    rv = next_interval(now, interval_s)
    # also accounts for hints being in the past / negative
    rv = max((rv,) + hints)

    rv = round_up(rv, interval_s)
    rv = apply_jitter(rv, interval_s, jitter)

    return rv


def next_interval(dt: datetime, interval: int) -> datetime:
    """Return the next interval.

    Ensure whole-week intervals start on Monday.

    """
    return from_timestamp((to_timestamp(dt) // interval + 1) * interval)


def round_up(dt: datetime, interval: int) -> datetime:
    """Round up to the next interval (no-op if already aligned).

    Ensure whole-week intervals start on Monday.

    """
    return from_timestamp(math.ceil(to_timestamp(dt) / interval) * interval)


def apply_jitter(dt: datetime, interval: int, jitter: float) -> datetime:
    jitter_s = random.random() * jitter * interval
    jitter_s = jitter_s // 60 * 60
    return dt + timedelta(seconds=jitter_s)


def to_timestamp(dt: datetime) -> float:
    return (dt - UPDATE_AFTER_EPOCH).total_seconds()


def from_timestamp(timestamp: float) -> datetime:
    offset = UPDATE_AFTER_EPOCH - UNIX_EPOCH
    return datetime.fromtimestamp(timestamp, timezone.utc) + offset


@dataclass
class Pipeline(PipelineBase[FeedData, EntryData, FeedUpdateIntent, EntryUpdateIntent]):
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

    decider = Decider

    def parse_feeds(self, feeds: Iterable[FeedForUpdate]) -> Iterable[ParseResult]:
        # ಠ_ಠ
        # The pipeline is not equipped to handle ParseErrors
        # as early as parser.process_feed_for_update().
        # So, we stash them away and don't retrieve/parse those feeds,
        # and then tack them on at the end of parse_results.
        # Storing the exceptions until the end of the generator
        # might cause memory issues, but the caller may need to raise them.
        # TODO: Rework update pipeline to support process_feed_for_update() exceptions.
        parse_errors: list[ParseResult] = []

        def parser_process_feeds_for_update(
            feeds: Iterable[FeedForUpdate],
        ) -> Iterable[FeedForUpdate]:
            for feed in feeds:
                try:
                    yield self.reader._parser.process_feed_for_update(feed)
                except ParseError as e:
                    parse_errors.append(ParseResult(feed, e))

        with make_pool_map(self.workers) as parallel_map:
            feeds = parser_process_feeds_for_update(feeds)
            feeds = map(self.decider.process_feed_for_update, feeds)
            parse_results = self.reader._parser.parallel(feeds, parallel_map)
            yield from chain(parse_results, parse_errors)

    def make_intents(
        self, result: ParseResult, entries: Iterable[EntryPair]
    ) -> tuple[FeedUpdateIntent, Iterable[EntryUpdateIntentPair]]:
        feed, value, *_ = result

        config_key = self.reader.make_reader_reserved_name(CONFIG_KEY)
        # TODO: get global config only once
        config = flatten_config(self.reader.get_tag((), config_key, {}), DEFAULT_CONFIG)
        # TODO: the feed tag value should come from get_feeds_for_update()
        config = flatten_config(self.reader.get_tag(feed, config_key, {}), config)

        if value and not isinstance(value, Exception):
            entries = self.reader._parser.process_entry_pairs(
                feed.url, value.mime_type, entries
            )

        return self.decider.make_intents(
            self.reader._now(),
            self.now,
            config,
            result,
            entries,
        )

    def store_feed(
        self, feed: FeedUpdateIntent, entries: Iterable[EntryUpdateIntent]
    ) -> None:
        if entries:
            self.reader._storage.add_or_update_entries(entries)
        self.reader._storage.update_feed(feed)

    def get_entry_resource_id(self, data: EntryData) -> tuple[str, str]:
        return data.resource_id

    def get_entry_data(self, intent: EntryUpdateIntent) -> EntryData:
        return intent.entry
