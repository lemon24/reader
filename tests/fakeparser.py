from collections import OrderedDict
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from datetime import timezone
from io import BytesIO

import reader._parser
from reader import ParseError
from reader._parser import NotModified
from reader._parser import ParsedFeed
from reader._parser import RetrievedFeed
from reader._types import EntryData
from reader._types import FeedData
from reader.types import _entry_argument


def _make_feed(number, updated=None, **kwargs):
    return FeedData(
        f'{number}',
        updated,
        kwargs.pop('title', f'Feed #{number}'),
        kwargs.pop('link', f'http://www.example.com/{number}'),
        **kwargs,
    )


def _make_entry(feed_number, number, updated=None, **kwargs):
    if isinstance(number, str):
        entry_number = number
    else:
        # evals to tuple
        entry_number = f'{feed_number}, {number}'
    return EntryData(
        f'{feed_number}',
        entry_number,
        updated,
        kwargs.pop('title', f'Entry #{number}'),
        kwargs.pop('link', f'http://www.example.com/entries/{number}'),
        **kwargs,
    )


@dataclass
class Parser:
    feeds: dict = field(default_factory=dict)
    entries: dict = field(default_factory=dict)
    caching_info: dict | None = None

    should_raise: callable or None = None
    exc: Exception = None
    is_not_modified: bool = False

    def copy(self):
        return deepcopy(self)

    def reset(self):
        self.feeds.clear()
        self.entries.clear()

    def feed(self, number, updated=None, **kwargs):
        feed = _make_feed(number, updated, **kwargs)
        self.feeds[number] = feed
        self.entries.setdefault(number, OrderedDict())
        return feed

    def entry(self, feed_number, number, updated=None, **kwargs):
        entry = _make_entry(feed_number, number, updated, **kwargs)
        self.entries[feed_number][number] = entry
        return entry

    def raise_exc(self, cond=None, exc=None):
        self.reset_mode()
        if isinstance(cond, Exception):
            assert not exc
            cond, exc = None, cond
        self.should_raise = cond or (lambda _: True)
        self.exc = exc or Exception('failing')
        return self

    def not_modified(self):
        self.reset_mode()
        self.is_not_modified = True
        return self

    def reset_mode(self):
        self.should_raise = None
        self.exc = None
        self.is_not_modified = False
        return self

    # parser API

    def __call__(self, url, caching_info):
        raise NotImplementedError

    parallel = reader._parser.Parser.parallel
    retrieve_fn = reader._parser.Parser.retrieve_fn
    parse_fn = reader._parser.Parser.parse_fn

    class session_factory:
        persistent = staticmethod(nullcontext)

    def retrieve(self, url, caching_info):
        if self.should_raise and self.should_raise(url):
            try:
                # We raise so the exception has a traceback set.
                raise self.exc
            except ParseError as e:
                raise
            except Exception as e:
                raise ParseError(url) from e
        if self.is_not_modified:
            raise NotModified(url)
        return nullcontext(RetrievedFeed(BytesIO(b'opaque')))

    def parse(self, url, retrieved):
        assert retrieved.resource.read() == b'opaque', retrieved

        for feed_number, feed in self.feeds.items():
            if feed.url == url:
                break
        else:
            raise RuntimeError(f"unkown feed: {url}")

        entries = list(self.entries[feed_number].values())

        return ParsedFeed(feed, entries, None, self.caching_info)

    def validate_url(self, url):
        pass

    def process_feed_for_update(self, feed):
        return feed

    def process_entry_pairs(self, url, mime_type, pairs):
        return pairs
