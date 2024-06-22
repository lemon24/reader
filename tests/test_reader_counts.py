import typing

import pytest

from fakeparser import Parser
from reader import Content
from reader import Enclosure
from reader import EntryCounts
from reader import FeedCounts
from reader import make_reader
from utils import rename_argument
from utils import utc_datetime as datetime


def kwargs_ids(val):
    if isinstance(val, dict):
        return ','.join(f'{k}={v!r}' for k, v in val.items())


KWARGS_AND_EXPECTED_FEED_COUNTS = [
    (dict(), FeedCounts(3, broken=1, updates_enabled=2)),
    (dict(feed='1'), FeedCounts(1, 0, 1)),
    (dict(tags=['tag']), FeedCounts(2, broken=1, updates_enabled=2)),
    (dict(broken=True), FeedCounts(1, broken=1, updates_enabled=1)),
    (dict(broken=False), FeedCounts(2, broken=0, updates_enabled=1)),
    (dict(updates_enabled=True), FeedCounts(2, broken=1, updates_enabled=2)),
    (dict(updates_enabled=False), FeedCounts(1, broken=0, updates_enabled=0)),
    (dict(broken=True, updates_enabled=False), FeedCounts(0, 0, 0)),
]


@pytest.fixture(scope='module')
def reader_feed_counts():
    with make_reader(':memory:') as reader:
        reader._parser = parser = Parser()

        one = parser.feed(1)
        two = parser.feed(2)
        three = parser.feed(3)

        for feed in one, two, three:
            reader.add_feed(feed)

        parser.raise_exc(lambda url: url == two.url)
        reader.disable_feed_updates(three)
        reader.set_tag(one, 'tag')
        reader.set_tag(two, 'tag')

        reader.update_feeds()

        yield reader


@pytest.mark.parametrize(
    'kwargs, expected', KWARGS_AND_EXPECTED_FEED_COUNTS, ids=kwargs_ids
)
@rename_argument('reader', 'reader_feed_counts')
def test_feed(reader, kwargs, expected):
    assert reader.get_feed_counts(**kwargs) == expected

    # sanity check
    assert len(list(reader.get_feeds(**kwargs))) == expected.total


def entries_per_day(month, quarter, year):
    return month / 30, quarter / 91, year / 365


KWARGS_AND_EXPECTED_ENTRY_COUNTS = [
    (
        dict(),
        EntryCounts(
            9,
            read=2,
            important=4,
            unimportant=1,
            has_enclosures=8,
            averages=entries_per_day(2, 3, 7),
        ),
    ),
    (
        dict(feed='1'),
        EntryCounts(
            1,
            read=0,
            important=0,
            unimportant=0,
            has_enclosures=0,
            averages=entries_per_day(0, 0, 1),
        ),
    ),
    (
        dict(feed='2'),
        EntryCounts(
            8,
            read=2,
            important=4,
            unimportant=1,
            has_enclosures=8,
            averages=entries_per_day(2, 3, 6),
        ),
    ),
    (
        dict(entry=('1', '1, 1')),
        EntryCounts(
            1,
            read=0,
            important=0,
            unimportant=0,
            has_enclosures=0,
            averages=entries_per_day(0, 0, 1),
        ),
    ),
    (
        dict(entry=('2', '2, 1')),
        EntryCounts(
            1,
            read=1,
            important=1,
            unimportant=0,
            has_enclosures=1,
            averages=entries_per_day(0, 0, 0),
        ),
    ),
    (
        dict(entry=('2', '2, 3')),
        EntryCounts(
            1,
            read=0,
            important=1,
            unimportant=0,
            has_enclosures=1,
            averages=entries_per_day(0, 0, 1),
        ),
    ),
    (
        dict(entry=('2', '2, 5')),
        EntryCounts(
            1,
            read=0,
            important=0,
            unimportant=0,
            has_enclosures=1,
            averages=entries_per_day(0, 0, 1),
        ),
    ),
    (
        dict(read=True),
        EntryCounts(
            2,
            read=2,
            important=2,
            unimportant=0,
            has_enclosures=2,
            averages=entries_per_day(1, 1, 1),
        ),
    ),
    (
        dict(read=False),
        EntryCounts(
            7,
            read=0,
            important=2,
            unimportant=1,
            has_enclosures=6,
            averages=entries_per_day(1, 2, 6),
        ),
    ),
    (
        dict(important=True),
        EntryCounts(
            4,
            read=2,
            important=4,
            unimportant=0,
            has_enclosures=4,
            averages=entries_per_day(1, 1, 2),
        ),
    ),
    (
        dict(important=False),
        EntryCounts(
            5,
            read=0,
            important=0,
            unimportant=1,
            has_enclosures=4,
            averages=entries_per_day(1, 2, 5),
        ),
    ),
    (
        dict(important='isfalse'),
        EntryCounts(
            1,
            read=0,
            important=0,
            unimportant=1,
            has_enclosures=1,
            averages=entries_per_day(1, 1, 1),
        ),
    ),
    (
        dict(has_enclosures=True),
        EntryCounts(
            8,
            read=2,
            important=4,
            unimportant=1,
            has_enclosures=8,
            averages=entries_per_day(2, 3, 6),
        ),
    ),
    (
        dict(has_enclosures=False),
        EntryCounts(
            1,
            read=0,
            important=0,
            unimportant=0,
            has_enclosures=0,
            averages=entries_per_day(0, 0, 1),
        ),
    ),
    (
        dict(feed_tags=['tag']),
        EntryCounts(
            1,
            read=0,
            important=0,
            unimportant=0,
            has_enclosures=0,
            averages=entries_per_day(0, 0, 1),
        ),
    ),
]


@pytest.fixture(scope='module')
def reader_entry_counts():
    # TODO: testing everything all at once like this is kinda brittle
    # https://github.com/lemon24/reader/pull/342#discussion_r1649614984

    with make_reader(':memory:') as reader:
        reader._parser = parser = Parser()

        one = parser.feed(1)
        two = parser.feed(2)
        three = parser.feed(3)

        one_entry = parser.entry(
            1,
            1,
            datetime(2011, 5, 15),
            summary='summary',
            content=(Content('value3', 'type', 'en'), Content('value2')),
        )

        # all have enclosures
        two_entries = [
            # important, read, not in averages because too old
            parser.entry(2, 1, datetime(2010, 1, 15), enclosures=[]),
            # not deduped with (1, 1) because different feed
            parser.entry(2, 2, datetime(2011, 5, 15), enclosures=[]),
            # important, deduped with 2 in averages because updated overlaps
            parser.entry(2, 3, datetime(2011, 5, 15), enclosures=[]),
            # important
            parser.entry(2, 4, datetime(2011, 8, 15), enclosures=[]),
            # not deduped with 4, because (published, updated, added) don't overlap
            parser.entry(
                2,
                5,
                datetime(2011, 9, 15),
                enclosures=[],
                published=datetime(2011, 8, 15),
            ),
            parser.entry(2, 6, datetime(2011, 11, 15), enclosures=[]),
            # unimportant, gets updated / added 2011-12-16 (_now() during update_feeds())
            parser.entry(2, 7, None, enclosures=[]),
            # important, read
            parser.entry(2, 8, datetime(2011, 12, 15), enclosures=[]),
        ]

        # TODO: less overlap would be nice (e.g. some read that don't have enclosures)

        for entry in two_entries[:8]:
            int_feed_url, int_id = eval(entry.id)
            parser.entries[int_feed_url][int_id].enclosures.append(
                Enclosure('http://e')
            )

        for feed in one, two, three:
            reader.add_feed(feed)

        reader.set_tag(one, 'tag')

        reader._now = lambda: datetime(2011, 12, 16)

        reader.update_feeds()
        reader.update_search()

        for entry in two_entries[:1]:
            reader.mark_entry_as_read(entry)
        reader.mark_entry_as_read(two_entries[-1])
        for entry in two_entries[:3]:
            reader.mark_entry_as_important(entry)
        reader.mark_entry_as_important(two_entries[-1])
        reader.mark_entry_as_unimportant(two_entries[-2])

        reader._now = lambda: datetime(2011, 12, 31)

        yield reader


@pytest.mark.parametrize(
    'kwargs, expected', KWARGS_AND_EXPECTED_ENTRY_COUNTS, ids=kwargs_ids
)
@rename_argument('reader', 'reader_entry_counts')
def test_entry(reader, get_entry_counts, kwargs, expected):
    actual = get_entry_counts(reader, **kwargs)
    assert type(actual) is typing.get_type_hints(get_entry_counts)['return']

    # this isn't gonna work as well if the return types get different attributes
    assert actual._asdict() == expected._asdict()

    # sanity_check
    assert len(list(get_entry_counts.get_entries(reader, **kwargs))) == expected.total
