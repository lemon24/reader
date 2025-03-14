from __future__ import annotations

import logging
import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from functools import partial
from itertools import chain
from itertools import tee
from typing import Any
from typing import NamedTuple
from typing import Optional
from typing import TYPE_CHECKING

from ._parser import ParseResult
from ._types import EntryData
from ._types import EntryForUpdate
from ._types import EntryUpdateIntent
from ._types import FeedData
from ._types import FeedForUpdate
from ._types import FeedToUpdate
from ._types import FeedUpdateIntent
from ._utils import count_consumed
from ._utils import PrefixLogger
from .exceptions import FeedNotFoundError
from .exceptions import ParseError
from .exceptions import UpdateError
from .types import EntryUpdateStatus
from .types import ExceptionInfo
from .types import UpdateConfig
from .types import UpdatedFeed
from .types import UpdateResult


if TYPE_CHECKING:  # pragma: no cover
    from ._parser import ParsedFeed
    from ._types import FeedFilter
    from ._utils import MapFunction
    from .core import Reader


log = logging.getLogger("reader")

HASH_CHANGED_LIMIT = 24


EntryPairs = Iterable[tuple[EntryData, Optional[EntryForUpdate]]]


@dataclass(frozen=True)
class Decider:
    """Decide whether a feed or entry should be updated.

    Does not interact with any dependencies, only processes data.

    This is an object only to make logging easier.

    """

    old_feed: FeedForUpdate
    now: datetime
    global_now: datetime
    config: UpdateConfig
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
            feed = feed._replace(updated=None, caching_info=None)
            log.info(
                "update feed %r: stale feed, ignoring updated and caching_info",
                feed.url,
            )
        return feed

    @classmethod
    def make_intents(
        cls,
        old_feed: FeedForUpdate,
        now: datetime,
        global_now: datetime,
        config: UpdateConfig,
        result: ParseResult[FeedForUpdate, ParseError],
        entry_pairs: EntryPairs,
    ) -> tuple[FeedUpdateIntent, Iterable[EntryUpdateIntent]]:
        decider = cls(
            old_feed,
            now,
            global_now,
            config,
            PrefixLogger(log, ["update feed %r" % old_feed.url]),
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
            self.log.info("feed has no last_updated, treating as updated")
            assert not old.updated, "updated must be None if last_updated is None"
            return True

        # Some feeds have entries newer than the feed;
        # we always update the feed if entries changed, for simplicity.
        # https://github.com/lemon24/reader/issues/76
        if entries_to_update:
            self.log.info("feed has entries to update, treating as updated")
            return True

        # Check if the feed content actually changed:
        # https://github.com/lemon24/reader/issues/179
        if not old.hash or new.hash != old.hash:
            self.log.info("feed hash changed, treating as updated")
            return True

        # For RSS feeds with no date element,
        # feedparser user lastBuildDate as .updated,
        # which can change without the feed actually changing,
        # so feed.updated is excluded from the hash.
        # https://github.com/lemon24/reader/issues/231#issuecomment-812601988
        if new.updated != old.updated:
            self.log.info("only feed updated changed, skipping")
            return False

        self.log.info("feed not updated, skipping")
        return False

    def should_update_entry(
        self, new: EntryData, old: EntryForUpdate | None
    ) -> UpdateReasons | None:
        def debug(msg: str, *args: Any) -> None:
            self.log.debug("entry %r: " + msg, new.id, *args)

        if self.stale:
            debug("feed marked as stale, updating")
            return UpdateReasons()

        if not old:
            debug("entry new, updating")
            return UpdateReasons()

        # entry.updated was excluded from hash for (fake) symmetry with feed.
        # https://github.com/lemon24/reader/issues/231#issuecomment-812601988
        # Unlike feed.updated, we always trust entry.updated (so far).
        if new.updated != old.updated:
            debug("entry updated, updating")
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
                debug("entry hash changed, updating")
                return UpdateReasons((old.hash_changed or 0) + 1)
            else:
                debug(
                    "entry hash changed, but exceeds the update limit (%i); skipping",
                    HASH_CHANGED_LIMIT,
                )
                return None

        debug("entry not updated, skipping")
        return None

    def get_entries_to_update(self, pairs: EntryPairs) -> Iterable[EntryUpdateIntent]:
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
                new=not old,
            )

    def get_feed_to_update(
        self,
        parsed_feed: ParsedFeed,
        entries_to_update: bool,
    ) -> FeedToUpdate | None:
        if self.should_update_feed(parsed_feed.feed, entries_to_update):
            return FeedToUpdate(parsed_feed.feed, self.now, parsed_feed.caching_info)
        return None

    def update(
        self,
        result: ParseResult[FeedForUpdate, ParseError],
        entry_pairs: EntryPairs,
    ) -> tuple[FeedUpdateIntent, Iterable[EntryUpdateIntent]]:

        # TODO: move entries_to_update in FeedToUpdate, maybe?
        entries_to_update: Iterable[EntryUpdateIntent] = ()
        value: FeedToUpdate | None | ExceptionInfo

        if not result.value:
            value = None
        elif isinstance(result.value, ParseError):
            value = ExceptionInfo.from_exception(result.value)
        else:
            entries_to_update = list(self.get_entries_to_update(entry_pairs))
            value = self.get_feed_to_update(result.value, bool(entries_to_update))

        update_after = next_update_after(self.global_now, **self.config)

        http_info = result.http_info
        if http_info and http_info.status in (429, 503) and http_info.retry_after:
            if isinstance(http_info.retry_after, datetime):
                retry_after = http_info.retry_after.astimezone(timezone.utc)
            else:
                retry_after = self.global_now + http_info.retry_after
            # also accounts for retry_after being in the past / negative
            if retry_after > update_after:
                # round up to the next interval
                update_after = next_update_after(retry_after, **self.config)

        # We always return a FeedUpdateIntent because
        # we always want to set last_retrieved and update_after,
        # and clear last_exception (if set before the update).

        return (
            FeedUpdateIntent(self.url, self.now, update_after, value),
            entries_to_update,
        )


class UpdateReasons(NamedTuple):
    hash_changed: int = 0


DEFAULT_CONFIG = UpdateConfig(interval=60, jitter=0)
CONFIG_KEY = 'update'


def flatten_config(config: Any, default: UpdateConfig) -> UpdateConfig:
    rv = default.copy()

    if not isinstance(config, dict):
        log.warning(
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
        log.warning("invalid update config .%s: %s", name, e)
        return

    if not (min <= value <= max):
        log.warning(
            "invalid update config .%s: must be between %s and %s: %s",
            name,
            min,
            max,
            value,
        )
        return

    dst[name] = value


# start on a Monday, so weekly amounts of seconds line up
UPDATE_AFTER_START = datetime(1970, 1, 5)
EPOCH_OFFSET = (UPDATE_AFTER_START - datetime(1970, 1, 1)).total_seconds()


def next_update_after(now: datetime, interval: int, jitter: float = 0) -> datetime:
    interval_s = interval * 60
    now_s = (now.replace(tzinfo=None) - UPDATE_AFTER_START).total_seconds()
    rv_s = int((now_s // interval_s + 1 + random.random() * jitter) * interval_s)
    rv_s = rv_s // 60 * 60
    rv = datetime.fromtimestamp(rv_s + EPOCH_OFFSET, timezone.utc).replace(
        tzinfo=now.tzinfo
    )
    return rv


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

    reader: Reader

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

    map: MapFunction[Any, Any]
    decider = Decider

    def update(self, filter: FeedFilter) -> Iterable[UpdateResult]:
        config_key = self.reader.make_reader_reserved_name(CONFIG_KEY)
        config = flatten_config(self.reader.get_tag((), config_key, {}), DEFAULT_CONFIG)

        process_parse_result = partial(self.process_parse_result, config)

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
                    yield self.reader._parser.process_feed_for_update(feed)
                except ParseError as e:
                    parser_process_feeds_for_update_errors.append(ParseResult(feed, e))

        # assemble pipeline
        feeds_for_update = self.reader._storage.get_feeds_for_update(filter)
        # feeds_for_update = map(self.parser.process_feed_for_update, feeds_for_update)
        feeds_for_update = parser_process_feeds_for_update(feeds_for_update)
        feeds_for_update = map(self.decider.process_feed_for_update, feeds_for_update)
        parse_results = self.reader._parser.parallel(feeds_for_update, self.map)
        parse_results = chain(parse_results, parser_process_feeds_for_update_errors)
        update_results = map(process_parse_result, parse_results)

        for url, value in update_results:
            if isinstance(value, FeedNotFoundError):
                log.info("update feed %r: feed removed during update", url)
                continue

            if isinstance(value, Exception):
                if not isinstance(value, UpdateError):
                    raise value

            yield UpdateResult(url, value)

    def process_parse_result(
        self,
        config: UpdateConfig,
        result: ParseResult[FeedForUpdate, ParseError],
    ) -> tuple[str, UpdatedFeed | None | Exception]:
        feed, value, _ = result

        # TODO: don't duplicate code from update()
        # TODO: the feed tag value should come from get_feeds_for_update()
        config_key = self.reader.make_reader_reserved_name(CONFIG_KEY)
        config = flatten_config(self.reader.get_tag(feed, config_key, {}), config)

        make_intents = partial(
            self.decider.make_intents,
            feed,
            self.reader._now(),
            self.global_now,
            config,
            result,
        )

        try:
            # assemble pipeline
            if value and not isinstance(value, Exception):
                entry_pairs = self.get_entry_pairs(value)
                entry_pairs = self.reader._parser.process_entry_pairs(
                    feed.url, value.mime_type, entry_pairs
                )
                entry_pairs, get_total_count = count_consumed(entry_pairs)
            else:
                entry_pairs = ()
                get_total_count = lambda: 0  # noqa: E731

            intents = make_intents(entry_pairs)
            counts = self.update_feed(*intents)
            total = get_total_count()

        except Exception as e:
            return feed.url, e

        if not value or isinstance(value, Exception):
            return feed.url, value

        return feed.url, UpdatedFeed(feed.url, *counts, total - sum(counts))

    def get_entry_pairs(self, result: ParsedFeed) -> EntryPairs:
        # give storage a chance to consume entries in a streaming fashion
        entries1, entries2 = tee(result.entries)
        entries_for_update = self.reader._storage.get_entries_for_update(
            (e.feed_url, e.id) for e in entries1
        )
        return zip(entries2, entries_for_update, strict=True)

    def update_feed(
        self,
        feed: FeedUpdateIntent,
        entries: Iterable[EntryUpdateIntent],
    ) -> tuple[int, int]:
        url = feed.url
        hooks = self.reader._update_hooks

        hooks.run('before_feed_update', (url,), url)

        if entries:
            self.reader._storage.add_or_update_entries(entries)
        self.reader._storage.update_feed(feed)

        # if feed_for_update.url != parsed_feed.feed.url, the feed was redirected.
        # TODO: Maybe handle redirects somehow else (e.g. change URL if permanent).

        with hooks.group("got unexpected after-update hook errors") as hook_errors:
            new_count = 0
            updated_count = 0
            for entry in entries:
                if entry.new:
                    new_count += 1
                    entry_status = EntryUpdateStatus.NEW
                else:
                    updated_count += 1
                    entry_status = EntryUpdateStatus.MODIFIED

                hook_errors.run(
                    'after_entry_update',
                    entry.entry.resource_id,
                    entry.entry,
                    entry_status,
                    limit=5,
                )

            hook_errors.run('after_feed_update', (url,), url)

        return new_count, updated_count
