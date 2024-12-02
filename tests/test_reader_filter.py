import pytest

from fakeparser import Parser
from reader import Enclosure
from reader import Entry
from reader import EntrySource
from reader import Feed
from reader import make_reader
from reader_methods import get_feeds
from utils import rename_argument
from utils import utc_datetime as datetime


# BEGIN tag filtering tests

ALL_IDS = {(1, 1), (1, 2), (2, 1), (3, 1)}

TAGS_AND_EXPECTED_IDS = [
    (None, ALL_IDS),
    (True, ALL_IDS - {(3, 1)}),
    (False, {(3, 1)}),
    ([True, False], set()),
    ([[True, False]], ALL_IDS),
    (['tag'], ALL_IDS - {(3, 1)}),
    (['-tag'], {(3, 1)}),
    (['unknown'], set()),
    (['-unknown'], ALL_IDS),
    (['first'], {(1, 1), (1, 2)}),
    (['second'], {(2, 1)}),
    (['first', 'second'], set()),
    ([['first', 'second']], {(1, 1), (1, 2), (2, 1)}),
    (['first', 'tag'], {(1, 1), (1, 2)}),
    (['second', 'tag'], {(2, 1)}),
    ([['first', 'second'], 'tag'], {(1, 1), (1, 2), (2, 1)}),
    ([['first'], ['tag']], {(1, 1), (1, 2)}),
    ([['first', 'tag']], {(1, 1), (1, 2), (2, 1)}),
    (['-first', 'tag'], {(2, 1)}),
    ([['first', '-tag']], ALL_IDS - {(2, 1)}),
    ([[False, 'first']], {(1, 1), (1, 2), (3, 1)}),
    ([True, '-first'], {(2, 1)}),
]


def setup_reader_for_tags(reader):
    reader._parser = parser = Parser()

    one = parser.feed(1)  # tag, first
    one_one = parser.entry(1, 1)
    one_two = parser.entry(1, 2)

    two = parser.feed(2)  # tag, second
    two_one = parser.entry(2, 1)

    three = parser.feed(3)  # <no tags>
    three_one = parser.entry(3, 1)

    for feed in one, two, three:
        reader.add_feed(feed)

    reader.update_feeds()
    reader.update_search()


@pytest.fixture(scope='module')
def reader_feed_tags():
    with make_reader(':memory:') as reader:
        setup_reader_for_tags(reader)

        reader.set_tag('1', 'tag')
        reader.set_tag('1', 'first')
        reader.set_tag('2', 'tag')
        reader.set_tag('2', 'second')

        yield reader


@pytest.fixture(scope='module')
def reader_entry_tags():
    with make_reader(':memory:') as reader:
        setup_reader_for_tags(reader)

        reader.set_tag(('1', '1, 1'), 'tag')
        reader.set_tag(('1', '1, 2'), 'tag')
        reader.set_tag(('1', '1, 1'), 'first')
        reader.set_tag(('1', '1, 2'), 'first')
        reader.set_tag(('2', '2, 1'), 'tag')
        reader.set_tag(('2', '2, 1'), 'second')

        yield reader


@pytest.mark.parametrize('tags, expected', TAGS_AND_EXPECTED_IDS)
@rename_argument('reader', 'reader_feed_tags')
def test_entries_by_feed_tags(reader, get_entries, tags, expected):
    actual = {eval(e.id) for e in get_entries(reader, feed_tags=tags)}
    assert actual == expected

    if tags is None:
        assert actual == {eval(e.id) for e in get_entries(reader)}

    assert get_entries.counts(reader, feed_tags=tags).total == len(actual)


# TODO: maybe test all the get_feeds sort orders (maybe fixture?)


@pytest.mark.parametrize('tags, expected', TAGS_AND_EXPECTED_IDS)
@rename_argument('reader', 'reader_feed_tags')
def test_feeds_by_feed_tags(reader, tags, expected):
    actual = {eval(f.url) for f in reader.get_feeds(tags=tags)}
    assert actual == {t[0] for t in expected}

    if tags is None:
        assert actual == {eval(f.url) for f in get_feeds(reader)}

    assert reader.get_feed_counts(tags=tags).total == len(actual)


@pytest.mark.parametrize('tags, expected', TAGS_AND_EXPECTED_IDS)
@rename_argument('reader', 'reader_entry_tags')
def test_entries_by_entry_tags(reader, get_entries, tags, expected):
    actual = {eval(e.id) for e in get_entries(reader, tags=tags)}
    assert actual == expected

    if tags is None:
        assert actual == {eval(e.id) for e in get_entries(reader)}

    assert get_entries.counts(reader, tags=tags).total == len(actual)


# END tag filtering tests


# BEGIN entry filtering tests

ALL_IDS = {
    (1, 1),
    (1, 2),
    (1, 3),
    (1, 4),
    (2, 1),
}


@pytest.fixture(scope='module')
def reader_entries():
    with make_reader(':memory:') as reader:
        reader._parser = parser = Parser()

        one = parser.feed(1)
        one_one = parser.entry(1, 1)
        one_two = parser.entry(1, 2)  # read
        one_three = parser.entry(1, 3)  # important
        one_four = parser.entry(1, 4, enclosures=[Enclosure('http://e2')])
        two = parser.feed(2)
        two_one = parser.entry(2, 1, source=EntrySource(url='source'))

        reader.add_feed(one.url)
        reader.add_feed(two.url)
        reader.update_feeds()
        reader.update_search()

        reader.mark_entry_as_read((one.url, one_two.id))
        reader.mark_entry_as_important((one.url, one_three.id))

        yield reader


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(), ALL_IDS),
        (dict(read=None), ALL_IDS),
        (dict(read=True), {(1, 2)}),
        (dict(read=False), ALL_IDS - {(1, 2)}),
        (dict(important=None), ALL_IDS),
        (dict(important=True), {(1, 3)}),
        (dict(important=False), ALL_IDS - {(1, 3)}),
        (dict(has_enclosures=None), ALL_IDS),
        (dict(has_enclosures=True), {(1, 4)}),
        (dict(has_enclosures=False), ALL_IDS - {(1, 4)}),
        (dict(feed=None), ALL_IDS),
        (dict(feed='1'), {(1, 1), (1, 2), (1, 3), (1, 4)}),
        (dict(feed='2'), {(2, 1)}),
        (dict(feed=Feed('2')), {(2, 1)}),
        (dict(feed='inexistent'), set()),
        (dict(entry=None), ALL_IDS),
        (dict(entry=('1', '1, 1')), {(1, 1)}),
        (dict(entry=('1', '1, 2')), {(1, 2)}),
        (dict(entry=Entry('1, 2', feed=Feed('1'))), {(1, 2)}),
        (dict(entry=('inexistent', 'also-inexistent')), set()),
        (dict(source='source'), {(2, 1)}),
        (dict(source=Feed('source')), {(2, 1)}),
    ],
)
@rename_argument('reader', 'reader_entries')
def test_entries(reader, get_entries, kwargs, expected):
    assert {eval(e.id) for e in get_entries(reader, **kwargs)} == expected

    # TODO: how do we test the combinations between arguments?


@pytest.mark.parametrize(
    'kwargs',
    [
        dict(read=object()),
        dict(important=object()),
        dict(has_enclosures=object()),
        dict(feed=object()),
        dict(entry=object()),
        dict(source=object()),
    ],
)
@rename_argument('reader', 'reader_entries')
def test_entries_error(reader, get_entries, kwargs):
    with pytest.raises(ValueError):
        list(get_entries(reader, **kwargs))


@pytest.fixture(scope='module', params=[None, datetime(2010, 1, 1)])
def reader_entries_important(request):
    with make_reader(':memory:') as reader:
        reader._parser = parser = Parser()

        reader.add_feed(parser.feed(1))
        one = parser.entry(1, 1)
        two = parser.entry(1, 2)
        reader.add_feed(parser.feed(2))
        three = parser.entry(2, 3)

        reader.update_feeds()
        reader.update_search()

        reader.set_entry_important(one, None, request.param)
        reader.set_entry_important(two, True, request.param)
        reader.set_entry_important(three, False, request.param)

        return reader


@pytest.mark.parametrize(
    'important, expected',
    [
        ('istrue', {'1, 2'}),
        (True, {'1, 2'}),
        ('isfalse', {'2, 3'}),
        ('notset', {'1, 1'}),
        ('nottrue', {'2, 3', '1, 1'}),
        (False, {'2, 3', '1, 1'}),
        ('notfalse', {'1, 2', '1, 1'}),
        ('isset', {'2, 3', '1, 2'}),
        ('any', {'1, 1', '2, 3', '1, 2'}),
        (None, {'1, 1', '2, 3', '1, 2'}),
    ],
)
@rename_argument('reader', 'reader_entries_important')
def test_entries_important(reader, get_entries, important, expected):
    actual = {e.id for e in get_entries(reader, important=important)}
    assert actual == expected
    assert get_entries.counts(reader, important=important).total == len(expected)


# TODO: ideally, systematize all filtering tests?

# END entry filtering tests


# BEGIN feed filtering tests


ALL_IDS = {1, 2, 3, 4}


@pytest.fixture(scope='module')
def reader_feeds():
    with make_reader(':memory:') as reader:
        reader._parser = parser = Parser()

        one = parser.feed(1)
        two = parser.feed(2)  # broken
        three = parser.feed(3)
        four = parser.feed(4)  # updates disabled

        parser.raise_exc(lambda url: url == two.url)

        for feed in one, two, three, four:
            reader.add_feed(feed)

        reader.disable_feed_updates(four)
        reader.update_feeds()

        yield reader


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(), ALL_IDS),
        (dict(feed='1'), {1}),
        (dict(feed=Feed('1')), {1}),
        (dict(broken=None), ALL_IDS),
        (dict(broken=True), {2}),
        (dict(broken=False), ALL_IDS - {2}),
        (dict(updates_enabled=None), ALL_IDS),
        (dict(updates_enabled=True), ALL_IDS - {4}),
        (dict(updates_enabled=False), {4}),
    ],
)
@rename_argument('reader', 'reader_feeds')
def test_feeds(reader, kwargs, expected):
    assert {eval(f.url) for f in reader.get_feeds(**kwargs)} == expected

    # TODO: how do we test the combinations between arguments?


@pytest.mark.parametrize(
    'kwargs',
    [
        dict(feed=object()),
        dict(broken=object()),
        dict(updates_enabled=object()),
        dict(new=object()),
        dict(scheduled=object()),
        dict(scheduled=None),
    ],
)
@rename_argument('reader', 'reader_feeds')
def test_feeds_error(reader, kwargs):
    with pytest.raises(ValueError):
        list(reader.get_feeds(**kwargs))


# END feed filtering tests
