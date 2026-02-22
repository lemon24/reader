import pytest

from fakeparser import Parser
from reader import Enclosure
from reader import Entry
from reader import EntrySource
from reader import Feed
from reader import make_reader
from reader_methods import get_feeds
from reader_methods import get_feeds_via_update
from utils import rename_argument
from utils import utc_datetime as datetime


def kwargs_ids(x):
    if not isinstance(x, dict):
        return None
    pairs = []
    for k, v in x.items():
        v_repr = repr(v)
        if not type(v).__module__ == 'builtins':
            if len(v_repr) > 10:
                v_repr = f"{type(v).__name__}(...)"
        pairs.append(f"{k}={v_repr}")
    return f"{{{','.join(pairs)}}}"


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
    reader._parser = parser = Parser().with_titles()

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
    'default',
    'read',
    'important',
    'unimportant',
    'enclosures',
    'source',
}


@pytest.fixture(scope='module')
def reader_entries():
    with make_reader(':memory:') as reader:
        reader._parser = parser = Parser().with_titles()

        one = parser.feed(1)
        default = parser.entry(1, 'default')
        read = parser.entry(1, 'read')
        important = parser.entry(1, 'important')
        unimportant = parser.entry(1, 'unimportant')
        enclosures = parser.entry(1, 'enclosures', enclosures=[Enclosure('http://e2')])
        two = parser.feed(2)
        source = parser.entry(2, 'source', source=EntrySource(url='source'))

        reader.add_feed(one)
        reader.add_feed(two)
        reader.update_feeds()
        reader.update_search()

        reader.mark_entry_as_read(read)
        reader.mark_entry_as_important(important)
        reader.mark_entry_as_unimportant(unimportant)

        yield reader


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(), ALL_IDS),
        (dict(read=None), ALL_IDS),
        (dict(read=True), {'read'}),
        (dict(read=False), ALL_IDS - {'read'}),
        (dict(important=None), ALL_IDS),
        (dict(important=True), {'important'}),
        (dict(important=False), ALL_IDS - {'important'}),
        (dict(important='istrue'), {'important'}),
        (dict(important='isfalse'), {'unimportant'}),
        (dict(important='notset'), ALL_IDS - {'important', 'unimportant'}),
        (dict(important='nottrue'), ALL_IDS - {'important'}),
        (dict(important='notfalse'), ALL_IDS - {'unimportant'}),
        (dict(important='isset'), {'important', 'unimportant'}),
        (dict(important='any'), ALL_IDS),
        (dict(has_enclosures=None), ALL_IDS),
        (dict(has_enclosures=True), {'enclosures'}),
        (dict(has_enclosures=False), ALL_IDS - {'enclosures'}),
        (dict(feed=None), ALL_IDS),
        (dict(feed='1'), ALL_IDS - {'source'}),
        (dict(feed='2'), {'source'}),
        (dict(feed=Feed('2')), {'source'}),
        (dict(feed='inexistent'), set()),
        (dict(entry=None), ALL_IDS),
        (dict(entry=('1', 'default')), {'default'}),
        (dict(entry=('1', 'read')), {'read'}),
        (dict(entry=Entry('read', feed=Feed('1'))), {'read'}),
        (dict(entry=('inexistent', 'idem')), set()),
        (dict(source='source'), {'source'}),
        (dict(source=Feed('source')), {'source'}),
    ],
    ids=kwargs_ids,
)
def test_entries(reader_entries, get_entries, kwargs, expected):
    reader = reader_entries
    assert {e.id for e in get_entries(reader, **kwargs)} == expected
    assert get_entries.counts(reader, **kwargs).total == len(expected)

    # TODO: how do we test the combinations between arguments?


@pytest.mark.parametrize(
    'kwargs',
    [
        dict(read=object()),
        dict(important=object()),
        dict(important='astring'),
        dict(has_enclosures=object()),
        dict(feed=object()),
        dict(entry=object()),
        dict(source=object()),
    ],
)
def test_entries_error(reader, get_entries, kwargs):
    with pytest.raises(ValueError):
        # raises before the iterable is consumed
        get_entries(reader, **kwargs)


# TODO: ideally, systematize all filtering tests?

# END entry filtering tests


# BEGIN feed filtering tests


ALL_FEEDS = {'normal', 'broken', 'disabled', 'new', 'scheduled'}


def setup_reader_for_feeds(reader, parser):
    reader._now = lambda: datetime(2010, 1, 1)
    scheduled = parser.feed('scheduled')
    reader.add_feed(scheduled)
    reader.update_feeds()

    reader._now = lambda: datetime(2010, 1, 2)
    normal = parser.feed('normal')
    broken = parser.feed('broken')
    parser.raise_exc(lambda url: url == 'broken')
    disabled = parser.feed('disabled')
    for feed in normal, broken, disabled:
        reader.add_feed(feed)
        try:
            reader.update_feed(feed)
        except Exception:
            assert feed is broken
    reader.disable_feed_updates('disabled')

    new = parser.feed('new')
    reader.add_feed(new)


@pytest.mark.parametrize(
    'kwargs, expected',
    [
        (dict(), ALL_FEEDS),
        (dict(feed='normal'), {'normal'}),
        (dict(feed=Feed('normal')), {'normal'}),
        (dict(broken=True), {'broken'}),
        (dict(broken=False), ALL_FEEDS - {'broken'}),
        (dict(updates_enabled=True), ALL_FEEDS - {'disabled'}),
        (dict(updates_enabled=False), {'disabled'}),
        (dict(new=True), {'new'}),
        (dict(new=False), ALL_FEEDS - {'new'}),
        (dict(scheduled=True), {'scheduled', 'new'}),
        (dict(scheduled=False), ALL_FEEDS),
    ],
    ids=kwargs_ids,
)
@pytest.mark.parametrize('get_feeds', [get_feeds, get_feeds_via_update])
def test_feeds(reader, parser, get_feeds, kwargs, expected):
    setup_reader_for_feeds(reader, parser)

    # need to get counts before get_feeds(), since it may do an update
    counts = get_feeds.counts(reader, **kwargs)
    urls = {f.url for f in get_feeds(reader, **kwargs)}

    assert urls == expected
    assert counts.total == len(expected)

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
def test_feeds_error(reader, kwargs):
    with pytest.raises(ValueError):
        # raises before the iterable is consumed
        reader.get_feeds(**kwargs)


# END feed filtering tests
