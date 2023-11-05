import threading
from collections import OrderedDict
from contextlib import nullcontext
from datetime import timezone
from io import BytesIO

import reader._parser
from reader import ParseError
from reader._parser import RetrieveResult
from reader._types import EntryData
from reader._types import FeedData
from reader._types import ParsedFeed
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


class Parser:
    tzinfo = timezone.utc

    def __init__(self, feeds=None, entries=None):
        self.feeds = feeds or {}
        self.entries = entries or {}
        self.http_etag = None
        self.http_last_modified = None

    @classmethod
    def from_parser(cls, other):
        return cls(other.feeds, other.entries)

    def feed(self, number, updated=None, **kwargs):
        feed = _make_feed(number, updated, **kwargs)
        self.feeds[number] = feed
        self.entries.setdefault(number, OrderedDict())
        return feed

    def entry(self, feed_number, number, updated=None, **kwargs):
        entry = _make_entry(feed_number, number, updated, **kwargs)
        self.entries[feed_number][number] = entry
        return entry

    def __call__(self, url, http_etag, http_last_modified):
        raise NotImplementedError

    parallel = reader._parser.Parser.parallel

    class session_factory:
        persistent = staticmethod(nullcontext)

    def retrieve(self, url, http_etag, http_last_modified, is_parallel):
        return nullcontext(RetrieveResult(BytesIO(b'opaque')))

    def parse(self, url, result):
        assert result.resource.read() == b'opaque', result

        for feed_number, feed in self.feeds.items():
            if feed.url == url:
                break
        else:
            raise RuntimeError(f"unkown feed: {url}")

        entries = list(self.entries[feed_number].values())

        return ParsedFeed(
            feed,
            entries,
            self.http_etag,
            self.http_last_modified,
        )

    def validate_url(self, url):
        pass

    def process_feed_for_update(self, feed):
        return feed

    def process_entry_pairs(self, url, mime_type, pairs):
        return pairs


class BlockingParser(Parser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.in_parser = threading.Event()
        self.can_return_from_parser = threading.Event()

    def wait(self):
        self.in_parser.set()
        self.can_return_from_parser.wait()

    def retrieve(self, *args):
        self.wait()
        return super().retrieve(*args)


class FailingParser(Parser):
    def __init__(self, *args, condition=lambda url: True, **kwargs):
        super().__init__(*args, **kwargs)
        self.condition = condition
        self.exception = Exception('failing')

    def raise_exc(self, url):
        if self.condition(url):
            try:
                # We raise so the exception has a traceback set.
                raise self.exception
            except Exception as e:
                raise ParseError(url) from e

    def retrieve(self, url, *args):
        self.raise_exc(url)
        return super().retrieve(url, *args)


class NotModifiedParser(Parser):
    def retrieve(self, *args):
        return nullcontext(None)


class ParserThatRemembers(Parser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def retrieve(self, *args):
        self.calls.append(args[:3])
        return super().retrieve(*args)

    # FIXME: remember parse() as well?
