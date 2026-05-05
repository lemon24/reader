from __future__ import annotations

import logging
from abc import ABC
from abc import abstractmethod
from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Generic
from typing import TYPE_CHECKING
from typing import TypeVar

from .._parser import EntryPairBase
from .._parser import ParsedFeedBase
from .._parser import ParseResultBase
from .._types import EntryData
from .._types import FeedFilter
from .._types import FeedForUpdate
from ..exceptions import FeedNotFoundError
from ..exceptions import ParseError
from ..exceptions import UpdateError
from ..types import EntryUpdateStatus
from ..types import UpdatedFeed
from ..types import UpdateResult

if TYPE_CHECKING:  # pragma: no cover
    from ..core import Reader

log = logging.getLogger("reader")


FD = TypeVar('FD')
ED = TypeVar('ED')
FI = TypeVar('FI')
EI = TypeVar('EI')

Result = ParseResultBase[FeedForUpdate, FD, ED, ParseError]
Feed = ParsedFeedBase[FD, ED]
Pair = EntryPairBase[ED]


class PipelineBase(Generic[FD, ED, FI, EI], ABC):
    """Run through high level update phases and call update hooks.

    Does not care how feed data is parsed, nor how it is persisted
    (useful for e.g. synchronizing feeds between databases).

    """

    reader: Reader

    @abstractmethod
    def parse(
        self, feeds_for_update: Iterable[FeedForUpdate]
    ) -> Iterable[Result[FD, ED]]:
        """Retrieve and parse an iterable of feeds, possibly in parallel."""

    @abstractmethod
    def make_intent(
        self, result: Result[FD, ED], entry_pairs: Iterable[Pair[ED]]
    ) -> tuple[FI, Iterable[Pair[EI]]]:
        """Transform a parse result into a feed update intent."""

    @abstractmethod
    def update_feed(self, feed: FI, entries: Iterable[EI]) -> None:
        """Save the update intents to storage."""

    @abstractmethod
    def get_entry_id(self, entry: ED) -> tuple[str, str]:
        """Return the entry id of an entry data."""

    @abstractmethod
    def get_entry_data(self, intent: EI) -> EntryData:
        """Transform an entry update intent into entry data (for plugins)."""

    def update(self, filter: FeedFilter) -> Iterable[UpdateResult]:
        feeds_for_update = self.reader._storage.get_feeds_for_update(filter)
        parse_results = self.parse(feeds_for_update)
        update_results = map(self.process_parse_result, parse_results)

        for url, value in update_results:
            if isinstance(value, FeedNotFoundError):
                log.info("update feed %r: feed removed during update", url)
                continue

            if isinstance(value, Exception):
                if not isinstance(value, UpdateError):
                    raise value

            yield UpdateResult(url, value)

    def process_parse_result(
        self, result: Result[FD, ED]
    ) -> tuple[str, UpdatedFeed | None | Exception]:
        feed, value, *_ = result

        try:
            entry_pairs = self.get_entry_pairs(result)
            feed_intent, entry_intents = self.make_intent(result, entry_pairs)
            entry_intents = list(entry_intents)

            with self.run_hooks(result.feed.url, entry_intents):
                self.update_feed(feed_intent, [new for new, _ in entry_intents])

        except Exception as e:
            return feed.url, e

        if not value or isinstance(value, Exception):
            return feed.url, value

        new = sum(1 for _, old in entry_intents if not old)

        return feed.url, UpdatedFeed(
            feed.url,
            new=new,
            modified=len(entry_intents) - new,
            unmodified=len(value.entries) - len(entry_intents),
        )

    def get_entry_pairs(self, result: Result[FD, ED]) -> Iterable[Pair[ED]]:
        if not result.value or isinstance(result.value, Exception):
            return []

        ids = map(self.get_entry_id, result.value.entries)
        entries_for_update = self.reader._storage.get_entries_for_update(ids)
        return zip(result.value.entries, entries_for_update, strict=True)

    @contextmanager
    def run_hooks(self, feed: str, entries: Iterable[Pair[EI]]) -> Iterator[None]:
        hooks = self.reader._update_hooks

        hooks.run('before_feed_update', (feed,), feed)

        yield

        with hooks.group("got unexpected after-update hook errors") as hook_errors:
            for new, old in entries:
                if not old:
                    entry_status = EntryUpdateStatus.NEW
                else:
                    entry_status = EntryUpdateStatus.MODIFIED

                entry = self.get_entry_data(new)

                hook_errors.run(
                    'after_entry_update',
                    entry.resource_id,
                    entry,
                    entry_status,
                    limit=5,
                )

            hook_errors.run('after_feed_update', (feed,), feed)
