from random import randrange

import pytest

from reader import Content
from reader import Entry
from reader.plugins.entry_dedupe import _is_duplicate_full
from reader.plugins.entry_dedupe import tokenize_content
from reader.plugins.entry_dedupe import tokenize_title
from utils import utc_datetime as datetime


@pytest.fixture
def reader(make_reader):
    return make_reader(':memory:', plugins=['reader.entry_dedupe'])


def test_duplicates_are_deleted(reader, parser):
    # detailed matching in test_is_duplicate

    reader.add_feed(parser.feed(1))

    yesterday = datetime(2010, 1, 1)
    parser.entry(1, 1, yesterday, title='title', summary='value')
    reader.update_feeds()

    today = datetime(2010, 1, 2)
    parser.entry(1, 2, today, title='title', summary='value')
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {'1, 2'}


def test_non_duplicates_are_ignored(reader, parser):
    # detailed matching in test_is_duplicate

    reader.add_feed(parser.feed(1))

    yesterday = datetime(2010, 1, 1)
    parser.entry(1, 1, None, title=None)
    parser.entry(1, 2, yesterday, title='title')
    parser.entry(1, 3, yesterday, summary='value')
    parser.entry(1, 4, yesterday, title='title', summary='another')
    parser.entry(1, 5, yesterday, title='another', summary='value')
    reader.update_feeds()

    today = datetime(2010, 1, 2)
    parser.entry(1, 6, today, title='title', summary='value')
    reader.update_feeds()

    assert {eval(e.id)[1] for e in reader.get_entries()} == {1, 2, 3, 4, 5, 6}


def test_duplicates_in_another_feed_are_ignored(reader, parser):
    reader.add_feed(parser.feed(1))
    reader.add_feed(parser.feed(2))

    yesterday = datetime(2010, 1, 1)
    parser.entry(1, 1, yesterday, title='title', summary='value')
    reader.update_feeds()

    today = datetime(2010, 1, 2)
    parser.entry(2, 1, today, title='title', summary='value')
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {'1, 1', '2, 1'}


def test_duplicates_change_during_update(reader, parser):
    reader.add_feed(parser.feed(1))

    yesterday = datetime(2010, 1, 1)
    parser.entry(1, 1, yesterday, title='title', summary='value')
    parser.entry(1, 2, yesterday, title='title', summary='old')
    reader.update_feeds()

    today = datetime(2010, 1, 2)
    parser.entry(1, 1, yesterday, title='title', summary='new')
    parser.entry(1, 2, yesterday, title='title', summary='value')
    parser.entry(1, 3, today, title='title', summary='value')
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {'1, 1', '1, 3'}


@pytest.mark.parametrize('read', [False, True])
@pytest.mark.parametrize('modified', [None, datetime(2010, 1, 1, 1)])
def test_read(reader, parser, read, modified):
    reader.add_feed(parser.feed(1))

    yesterday = datetime(2010, 1, 1)
    one = parser.entry(1, 1, yesterday, title='title', summary='value')
    reader.update_feeds()

    reader.set_entry_read(one, read, modified)

    today = datetime(2010, 1, 2)
    two = parser.entry(1, 2, today, title='title', summary='value')
    reader.update_feeds()

    two = reader.get_entry(two)
    assert two.read == read
    assert two.read_modified == modified

    # TODO: simplify test_read_modified_copying


@pytest.mark.parametrize('important', [False, None, True])
@pytest.mark.parametrize('modified', [None, datetime(2010, 1, 1, 1)])
def test_important(reader, parser, important, modified):
    reader.add_feed(parser.feed(1))

    yesterday = datetime(2010, 1, 1)
    one = parser.entry(1, 1, yesterday, title='title', summary='value')
    reader.update_feeds()

    reader.set_entry_important(one, important, modified)

    today = datetime(2010, 1, 3)
    two = parser.entry(1, 2, today, title='title', summary='value')
    reader.update_feeds()

    two = reader.get_entry(two)
    assert two.important == important
    assert two.important_modified == modified

    # TODO: simplify test_important_modified_copying


@pytest.mark.parametrize(
    'tags, expected',
    [
        ([], {3, 4}),
        (['once'], {2, 4}),
        (['once.title'], {2}),
        (['once', 'once.title'], {2, 4}),
    ],
    ids=lambda p: ','.join(map(str, p)),
)
def test_dedupe_once(make_reader, db_path, parser, tags, expected):
    reader = make_reader(db_path)

    feed = parser.feed(1)
    reader.add_feed(feed)
    reader.set_tag(feed, 'unrelated')

    parser.entry(1, 1, datetime(2010, 1, 1), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 1, 1)
    reader.update_feeds()

    parser.entry(1, 3, datetime(2010, 1, 3), title='title', summary='value')
    parser.entry(1, 4, datetime(2010, 1, 4), title='title')
    reader._now = lambda: datetime(2010, 1, 3, 1)
    reader.update_feeds()

    parser.entry(1, 2, datetime(2010, 1, 2), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 4, 1)
    reader.update_feeds()

    assert {eval(e.id)[1] for e in reader.get_entries()} == {1, 2, 3, 4}

    reader = make_reader(db_path, plugins=['reader.entry_dedupe'])

    # which entry is "latest" differs between .dedupe.once and normal duplicate
    if tags:
        for tag in tags:
            reader.set_tag(feed, f".reader.dedupe.{tag}")
    else:
        parser.entry(1, 0, datetime(2010, 1, 1), title='title', summary='value')

    reader._now = lambda: datetime(2010, 1, 5, 1)
    reader.update_feeds()

    assert {eval(e.id)[1] for e in reader.get_entries()} == expected
    assert set(reader.get_tag_keys(feed)) == {'unrelated'}


def make_entry(title=None, summary=None, content=None):
    entry = Entry('id', None, title=title, summary=summary)
    if content:
        entry = entry._replace(content=[Content(*content)])
    return entry


IS_DUPLICATE_DATA = [
    (make_entry(), make_entry(), False),
    (make_entry(title='title'), make_entry(title='title'), False),
    (make_entry(summary='summary'), make_entry(summary='summary'), False),
    (
        make_entry(content=('value', 'text/html')),
        make_entry(content=('value', 'text/html')),
        False,
    ),
    (
        make_entry(title='title', summary='summary'),
        make_entry(title='title', summary='summary'),
        True,
    ),
    (
        make_entry(title='title', summary='summary'),
        make_entry(title='other', summary='summary'),
        False,
    ),
    (
        make_entry(title='title', summary='summary'),
        make_entry(title='title', summary='other'),
        False,
    ),
    (
        make_entry(title='title', content=('value', 'text/html')),
        make_entry(title='title', content=('value', 'text/html')),
        True,
    ),
    (
        make_entry(title='title', content=('value', 'text/html')),
        make_entry(title='other', content=('value', 'text/html')),
        False,
    ),
    (
        make_entry(title='title', content=('value', 'text/html')),
        make_entry(title='title', content=('other', 'text/html')),
        False,
    ),
    (
        make_entry(title='title', content=('value', 'text/plain')),
        make_entry(title='title', content=('value', 'text/plain')),
        True,
    ),
    (
        make_entry(title='title', summary='value'),
        make_entry(title='title', content=('value', 'text/html')),
        True,
    ),
    (
        make_entry(title='title', summary='value'),
        make_entry(title='title', content=('value', 'text/html')),
        True,
    ),
    (
        make_entry(title='title', summary='one ' * 40),
        make_entry(title='title', summary='one ' * 39 + 'two '),
        True,
    ),
    (
        make_entry(title='title', summary='one ' * 40),
        make_entry(title='title', summary='one ' * 38),
        True,
    ),
    (
        make_entry(title='title', summary='one ' * 40),
        make_entry(title='title', summary='one ' * 20 + 'two ' * 3 + 17 * 'one '),
        False,
    ),
    (
        make_entry(title='title', summary='one ' * 50),
        make_entry(
            title='title', summary='one ' * 30 + 'two ' + 17 * 'one ' + 'three '
        ),
        True,
    ),
    (
        make_entry(title='title', summary='one ' * 50),
        make_entry(title='title', summary='one ' * 30 + 'two ' * 5 + 25 * 'one '),
        False,
    ),
    (
        make_entry(title='title', summary='one ' * 70),
        make_entry(
            title='title', summary='one ' * 30 + 'two ' * 5 + 33 * 'one ' + 'three '
        ),
        True,
    ),
    (
        make_entry(title='title', summary='one ' * 70),
        make_entry(title='title', summary='one ' * 30 + 'two ' * 10 + 30 * 'one '),
        False,
    ),
    # TODO: test normalization
]


@pytest.mark.parametrize('one, two, result', IS_DUPLICATE_DATA)
def test_is_duplicate(one, two, result):
    assert bool(_is_duplicate_full(one, two)) is bool(result)


READ_MODIFIED_COPYING_DATA = [
    # sanity checks
    ([], []),
    ([(1, False, None)], [(1, False, None)]),
    # some read, earliest modified of the read entries is used
    (
        [
            (1, False, None),
            (2, True, None),
            (3, False, datetime(2010, 1, 3)),
            (4, True, datetime(2010, 1, 4)),
            (5, True, datetime(2010, 1, 5)),
            (6, False, datetime(2010, 1, 6)),
            (9, False, None),
        ],
        [
            (9, True, datetime(2010, 1, 4)),
        ],
    ),
    # none read, earliest modified of the unread entries is used
    (
        [
            (1, False, None),
            (2, False, datetime(2010, 1, 2)),
            (3, False, datetime(2010, 1, 3)),
            (9, False, None),
        ],
        [
            (9, False, datetime(2010, 1, 2)),
        ],
    ),
    # none read, no modified
    (
        [
            (1, False, None),
            (9, False, None),
        ],
        [
            (9, False, None),
        ],
    ),
    # old read, no modified
    (
        [
            (1, True, None),
            (9, False, None),
        ],
        [
            (9, True, None),
        ],
    ),
    # new read, no modified
    (
        [
            (1, False, None),
            (9, True, None),
        ],
        [
            (9, True, None),
        ],
    ),
    # all read, earliest modified of the read entries is used (last has modified)
    (
        [
            (1, True, None),
            (2, True, datetime(2010, 1, 2)),
            (3, True, datetime(2010, 1, 3)),
        ],
        [
            (3, True, datetime(2010, 1, 2)),
        ],
    ),
    # none read, earliest modified of the unread entries is used (last has modified)
    (
        [
            (1, False, None),
            (2, False, datetime(2010, 1, 2)),
            (3, False, datetime(2010, 1, 3)),
        ],
        [
            (3, False, datetime(2010, 1, 2)),
        ],
    ),
]


@pytest.fixture(params=[False, True])
def same_last_updated(request):
    yield request.param


@pytest.mark.parametrize('data, expected', READ_MODIFIED_COPYING_DATA)
def test_read_modified_copying(
    make_reader, db_path, parser, data, expected, same_last_updated
):
    _test_modified_copying(
        make_reader, db_path, parser, data, expected, 'read', same_last_updated
    )


IMPORTANT_MODIFIED_COPYING_DATA = [
    # sanity checks
    ([], []),
    ([(1, False, None)], [(1, False, None)]),
    # none important, no modified
    (
        [
            (1, False, None),
            (9, False, None),
        ],
        [
            (9, False, None),
        ],
    ),
    # old important, no modified
    (
        [
            (1, True, None),
            (9, False, None),
        ],
        [
            (9, True, None),
        ],
    ),
    # new important, no modified
    (
        [
            (1, False, None),
            (9, True, None),
        ],
        [
            (9, True, None),
        ],
    ),
    # none important, modified
    (
        [
            (1, False, datetime(2010, 1, 1)),
            (9, False, None),
        ],
        [
            (9, False, datetime(2010, 1, 1)),
        ],
    ),
    # none important, modified (last has modified)
    (
        [
            (1, False, datetime(2010, 1, 1)),
            (9, False, datetime(2010, 1, 9)),
        ],
        [
            (9, False, datetime(2010, 1, 1)),
        ],
    ),
    # none important, modified (last has modified, same date)
    (
        [
            (1, False, datetime(2010, 1, 1)),
            (9, False, datetime(2010, 1, 1)),
        ],
        [
            (9, False, datetime(2010, 1, 1)),
        ],
    ),
    # old important, modified
    (
        [
            (1, True, datetime(2010, 1, 1)),
            (9, False, None),
        ],
        [
            (9, True, datetime(2010, 1, 1)),
        ],
    ),
    # new important, old modified
    (
        [
            (1, False, datetime(2010, 1, 1)),
            (9, True, None),
        ],
        [
            (9, True, None),
        ],
    ),
    # None vs False combos (subset of the above)
    # TODO: find a better way?
    # none set, modified (last has modified)
    (
        [
            (1, None, datetime(2010, 1, 1)),
            (9, None, datetime(2010, 1, 9)),
        ],
        [
            (9, None, datetime(2010, 1, 1)),
        ],
    ),
    # old unimportant, modified; new unset
    (
        [
            (1, False, datetime(2010, 1, 1)),
            (9, None, None),
        ],
        [
            (9, False, datetime(2010, 1, 1)),
        ],
    ),
    # new unimportant, old modified
    (
        [
            (1, None, datetime(2010, 1, 1)),
            (9, False, None),
        ],
        [
            (9, False, None),
        ],
    ),
    # None vs True combos (subset of the above)
    # TODO: find a better way?
    # old important, modified; new unset
    (
        [
            (1, True, datetime(2010, 1, 1)),
            (9, None, None),
        ],
        [
            (9, True, datetime(2010, 1, 1)),
        ],
    ),
    # new important, old modified
    (
        [
            (1, None, datetime(2010, 1, 1)),
            (9, True, None),
        ],
        [
            (9, True, None),
        ],
    ),
]


@pytest.mark.parametrize('data, expected', IMPORTANT_MODIFIED_COPYING_DATA)
def test_important_modified_copying(
    make_reader, db_path, parser, data, expected, same_last_updated
):
    _test_modified_copying(
        make_reader, db_path, parser, data, expected, 'important', same_last_updated
    )


def _test_modified_copying(
    make_reader, db_path, parser, data, expected, name, same_last_updated
):
    reader = make_reader(db_path)

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed)

    same_last_updated = False

    if not same_last_updated:
        # if .last_updated differs,
        # the entry with the most recent .last_updated remains

        for day_i, (id, *_) in enumerate(data, 1):
            reader._now = lambda: datetime(2010, 1, day_i)
            # updated doesn't matter, this should never make the test fail
            updated = datetime(2010, 1, randrange(1, 30))
            parser.entry(1, id, updated, title='title', summary='summary')
            reader.update_feeds()

    else:
        # if .last_updated is the same for all entries,
        # the order from get_entries(sort='recent') is preserved;
        # in this case, the entry with the most recent .updated remains

        reader._now = lambda: datetime(2010, 1, 1)
        for day_i, (id, *_) in enumerate(data, 1):
            parser.entry(
                1, id, datetime(2010, 1, day_i), title='title', summary='summary'
            )
        reader.update_feeds()

    reader._now: lambda: datetime(2011, 1, 1)

    # the entry with the highest id is the last one
    for id, flag, modified in data:
        getattr(reader, f'set_entry_{name}')(('1', f'1, {id}'), flag, modified)

    reader = make_reader(db_path, plugins=['reader.entry_dedupe'])
    reader.set_tag(feed, '.reader.dedupe.once')
    reader.update_feeds()

    actual = sorted(
        (eval(e.id)[1], getattr(e, name), getattr(e, f'{name}_modified'))
        for e in reader.get_entries()
    )
    assert actual == expected


COMPLEX_TAGS = {'tag': {'string': [10, True]}}

# [one [two]] three three_expected
ENTRY_TAGS_COPYING_DATA = [
    ({}, {}),
    (dict(tag=None), dict(tag=None)),
    (dict(tag=None), {}, dict(tag=None)),
    (dict(tag=None), dict(tag=None), {}, dict(tag=None)),
    (COMPLEX_TAGS, COMPLEX_TAGS, COMPLEX_TAGS, COMPLEX_TAGS),
    (dict(tag='one'), {}, dict(tag='one')),
    (
        dict(tag='one'),
        dict(tag='two'),
        {},
        {
            'tag': 'two',
            '.reader.duplicate.1.of.tag': 'one',
        },
    ),
    (
        dict(tag='one'),
        dict(tag='two'),
        dict(tag='three'),
        {
            'tag': 'three',
            '.reader.duplicate.1.of.tag': 'two',
            '.reader.duplicate.2.of.tag': 'one',
        },
    ),
    (
        dict(tag='one'),
        dict(tag='three'),
        {
            'tag': 'three',
            '.reader.duplicate.1.of.tag': 'one',
        },
    ),
    (
        dict(tag='one'),
        {
            'tag': 'two',
            '.reader.duplicate.1.of.tag': 'three',
        },
        {
            'tag': 'two',
            '.reader.duplicate.1.of.tag': 'three',
            '.reader.duplicate.2.of.tag': 'one',
        },
    ),
    (
        dict(tag='one'),
        {
            'tag': 'two',
            '.reader.duplicate.2.of.tag': 'three',
        },
        {
            'tag': 'two',
            '.reader.duplicate.1.of.tag': 'one',
            '.reader.duplicate.2.of.tag': 'three',
        },
    ),
    (
        dict(tag='one'),
        {
            'tag': 'two',
            '.reader.duplicate.1.of.tag': 'one',
        },
        {
            'tag': 'two',
            '.reader.duplicate.1.of.tag': 'one',
        },
    ),
    (
        {
            'tag': 'two',
            '.reader.duplicate.1.of.tag': 'one',
        },
        {
            'tag': 'four',
            '.reader.duplicate.1.of.tag': 'three',
        },
        {
            'tag': 'four',
            '.reader.duplicate.1.of.tag': 'three',
            '.reader.duplicate.2.of.tag': 'one',
            '.reader.duplicate.3.of.tag': 'two',
        },
    ),
]


@pytest.mark.parametrize('tags', ENTRY_TAGS_COPYING_DATA)
def test_entry_tags_copying(make_reader, db_path, parser, tags):
    *old_tags, new_tags, expected_tags = tags

    reader = make_reader(db_path)
    feed = parser.feed(1)
    one = parser.entry(1, 1, datetime(2010, 1, 1), title='title', summary='summary')
    two = parser.entry(1, 2, datetime(2010, 1, 2), title='title', summary='summary')
    three = parser.entry(1, 3, datetime(2010, 1, 3), title='title', summary='summary')
    reader.add_feed(feed)
    reader.update_feeds()

    for entry, tags in list(zip([one, two], old_tags)) + [(three, new_tags)]:
        for key, value in tags.items():
            reader.set_tag(entry, key, value)

    reader = make_reader(db_path, plugins=['reader.entry_dedupe'])
    reader.set_tag(feed, '.reader.dedupe.once')
    reader.update_feeds()

    assert not list(reader.get_tag_keys(one))
    assert not list(reader.get_tag_keys(two))
    assert dict(reader.get_tags(three)) == expected_tags


# TODO: with_maybe_published_or_updated
def test_recent_sort_copying(make_reader, db_path, parser):
    reader = make_reader(db_path)
    reader.add_feed(parser.feed(1))

    parser.entry(1, 1, title='title', summary='summary')
    reader._now = lambda: datetime(2010, 1, 10)
    reader.update_feeds()

    parser.entry(1, 2, title='title', summary='summary')
    parser.entry(1, 3, title='other')
    reader._now = lambda: datetime(2010, 1, 20)
    reader.update_feeds()

    reader = make_reader(db_path, plugins=['reader.entry_dedupe'])

    del parser.entries[1][1]
    del parser.entries[1][2]
    four = parser.entry(1, 4, title='title', summary='summary')
    reader._now = lambda: datetime(2010, 2, 1)
    reader.update_feeds()

    assert [eval(e.id)[1] for e in reader.get_entries(sort='recent')] == [3, 4]

    actual_recent_sort = reader._storage.get_entry_recent_sort(four.resource_id)
    assert actual_recent_sort == datetime(2010, 1, 10)


@pytest.mark.parametrize('update_after_one', [False, True])
@pytest.mark.parametrize('with_dates, expected_id', [(False, '3'), (True, '2')])
def test_duplicates_in_feed(
    make_reader, parser, update_after_one, with_dates, expected_id
):
    reader = make_reader(':memory:', plugins=['reader.entry_dedupe'])

    reader.add_feed(parser.feed(1))
    # force recent_sort logic to use current times, not updated/published
    reader.update_feeds()

    one = parser.entry(1, '1', title='title', summary='summary')
    if update_after_one:
        reader._now = lambda: datetime(2009, 12, 1)
        reader.update_feeds()
        parser.entries[1].clear()
        reader.mark_entry_as_read(one)
        reader.mark_entry_as_important(one)
        reader.set_tag(one, 'key', 'value')

    parser.entry(
        1,
        '2',
        title='title',
        summary='summary',
        updated=datetime(2010, 1, 2) if with_dates else None,
    )
    parser.entry(
        1,
        '3',
        title='title',
        summary='summary',
        published=datetime(2010, 1, 1) if with_dates else None,
    )

    reader._now = lambda: datetime(2010, 1, 2, 12)

    # shouldn't fail
    reader.update_feeds()
    assert {e.id for e in reader.get_entries()} == {expected_id}

    reader._now = lambda: datetime(2010, 1, 2, 18)

    # shouldn't flip flop
    # https://github.com/lemon24/reader/issues/340
    reader.update_feeds()
    assert {e.id for e in reader.get_entries()} == {expected_id}

    entry = reader.get_entry(('1', expected_id))
    rs = reader._storage.get_entry_recent_sort(entry.resource_id)
    if update_after_one:
        assert entry.read
        assert entry.important
        assert dict(reader.get_tags(entry)) == {'key': 'value'}
        assert rs == datetime(2009, 12, 1)
    else:
        assert rs == datetime(2010, 1, 2, 12)


@pytest.mark.parametrize('tokenize', [tokenize_title, tokenize_content])
@pytest.mark.parametrize(
    'input, expected',
    [
        ('\n\n foo  Bar  ', ('foo', 'bar')),
        ('<b>foo</B> &nbsp; bar</p>', ('foo', 'bar')),
        ('Ará Orún', ('ara', 'orun')),
        ('汉语 漢語', ('汉语', '漢語')),
        ('1.0, 1.0.dev0; 2020-10-10', ('1.0', '1.0.dev0', '2020-10-10')),
        ('1.2.3.4 11.22.33.44', ('1.2.3', '4', '11.22.33', '44')),
    ],
)
def test_tokenize(tokenize, input, expected):
    assert tokenize(input) == expected
