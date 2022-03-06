from random import randrange

import pytest
from fakeparser import Parser
from utils import naive_datetime
from utils import utc_datetime as datetime

from reader import Content
from reader import Entry
from reader.plugins.entry_dedupe import _is_duplicate_full
from reader.plugins.entry_dedupe import _normalize


def test_normalize():
    assert _normalize('\n\n<B>whatever</B>&nbsp; Blah </p>') == 'whatever blah'


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


def test_plugin(make_reader):
    reader = make_reader(':memory:', plugins=['reader.entry_dedupe'])
    reader._parser = parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed)

    old = parser.entry(1, 1, datetime(2010, 1, 1), title='title', summary='old')
    title_only_one = parser.entry(1, 2, datetime(2010, 1, 1), title='title only')
    read_one = parser.entry(1, 3, datetime(2010, 1, 1), title='title', summary='read')
    unread_one = parser.entry(
        1, 4, datetime(2010, 1, 1), title='title', summary='unread'
    )
    important_one = parser.entry(
        1, 5, datetime(2010, 1, 1), title='important', summary='also important'
    )
    modified_one = parser.entry(
        1, 6, datetime(2010, 1, 1), title='title', summary='will be modified'
    )

    reader.update_feeds()
    reader.mark_entry_as_read(read_one)
    reader.mark_entry_as_important(important_one)

    feed = parser.feed(1, datetime(2010, 1, 2))
    new = parser.entry(1, 11, datetime(2010, 1, 2), title='title', summary='new')
    title_only_two = parser.entry(1, 12, datetime(2010, 1, 2), title='title only')
    read_two = parser.entry(1, 13, datetime(2010, 1, 2), title='title', summary='read')
    unread_two = parser.entry(
        1, 14, datetime(2010, 1, 2), title='title', summary='unread'
    )
    important_two = parser.entry(
        1, 15, datetime(2010, 1, 2), title='important', summary='also important'
    )
    modified_two = parser.entry(
        1, 6, datetime(2010, 1, 1), title='title', summary='was modified'
    )

    reader.update_feeds()

    assert set((e.id, e.read, e.important) for e in reader.get_entries()) == {
        t + (False,)
        for t in {
            # remain untouched
            (old.id, False),
            (new.id, False),
            # also remain untouched
            (title_only_one.id, False),
            (title_only_two.id, False),
            # the new one is marked as read because the old one was;
            # the old one is deleted
            (read_two.id, True),
            # the old one is deleted in favor of the new one
            (unread_two.id, False),
            # modified entry is ignored by plugin
            (modified_one.id, False),
        }
    } | {
        # the new one is important because the old one was;
        # the old one is deleted
        (important_two.id, False, True),
    }


@pytest.mark.parametrize(
    'tags',
    [
        ['.reader.dedupe.once'],
        ['.reader.dedupe.once.title'],
        ['.reader.dedupe.once', '.reader.dedupe.once.title'],
    ],
)
def test_plugin_once(make_reader, db_path, monkeypatch, tags):
    reader = make_reader(db_path)
    reader._parser = parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed)

    different_title = parser.entry(
        1, 1, datetime(2010, 1, 5), title='different title', summary='summary'
    )
    no_content_match = parser.entry(
        1, 2, datetime(2010, 1, 10), title='title', summary='does not match'
    )

    read_one = parser.entry(1, 4, datetime(2010, 1, 1), title='title', summary='read')
    read_two = parser.entry(
        1,
        6,
        datetime(2010, 1, 3),
        title='title',
        content=[Content('read', type='text/html')],
    )

    important_one = parser.entry(
        1, 9, datetime(2010, 1, 3), title='title', summary='important'
    )
    important_two = parser.entry(
        1,
        8,
        datetime(2010, 1, 1),
        title='title',
        content=[Content('important', type='text/plain')],
    )

    unread_one = parser.entry(
        1, 10, datetime(2010, 1, 1), title='title', content=[Content('unread')]
    )
    unread_two = parser.entry(
        1, 11, datetime(2010, 1, 1), title='title', summary='unread'
    )

    reader._now = lambda: naive_datetime(2010, 1, 10)
    reader.update_feeds()
    reader.mark_entry_as_read(read_one)

    read_three = parser.entry(1, 5, datetime(2010, 1, 2), title='title', summary='read')
    important_three = parser.entry(
        1, 7, datetime(2010, 1, 2), title='title', summary='important'
    )

    reader._now = lambda: naive_datetime(2010, 1, 11)
    reader.update_feeds()
    reader.mark_entry_as_important(important_two)

    unread_three = parser.entry(
        1, 12, datetime(2010, 1, 1), title='title', summary='unread'
    )

    reader._now = lambda: naive_datetime(2010, 1, 12)
    reader.update_feeds()

    reader = make_reader(db_path, plugins=['reader.entry_dedupe'])
    reader._parser = parser
    reader._now = lambda: naive_datetime(2010, 1, 12)
    reader.update_feeds()

    # nothing changes without tag
    assert set((e.id, e.read, e.important) for e in reader.get_entries()) == {
        (different_title.id, False, False),
        (no_content_match.id, False, False),
        (read_one.id, True, False),
        (read_two.id, False, False),
        (read_three.id, False, False),
        (important_one.id, False, False),
        (important_two.id, False, True),
        (important_three.id, False, False),
        (unread_one.id, False, False),
        (unread_two.id, False, False),
        (unread_three.id, False, False),
    }

    for tag in tags:
        reader.set_tag(feed, tag)
    reader.set_tag(feed, 'unrelated')
    reader.update_feeds()

    assert set(reader.get_tag_keys(feed)) == {'unrelated'}

    # if both 'once' and 'once.title' are in tags,
    # 'once' (the strictest) has priority
    if '.reader.dedupe.once' in tags:
        expected = {
            (different_title.id, False, False),
            (no_content_match.id, False, False),
            # delete read_one, read_two (older last_updated)
            (read_three.id, True, False),
            # delete important_one, important_two have (older last_updated)
            (important_three.id, False, True),
            # delete unread_one, unread_two (older last_updated)
            (unread_three.id, False, False),
        }
    else:
        expected = {
            (different_title.id, False, False),
            # delete all others (older last_updated)
            (unread_three.id, True, True),
        }

    assert set((e.id, e.read, e.important) for e in reader.get_entries()) == expected


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
def test_read_modified_copying(make_reader, db_path, data, expected, same_last_updated):
    _test_modified_copying(
        make_reader, db_path, data, expected, 'read', same_last_updated
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
]


@pytest.mark.parametrize('data, expected', IMPORTANT_MODIFIED_COPYING_DATA)
def test_important_modified_copying(
    make_reader, db_path, data, expected, same_last_updated
):
    _test_modified_copying(
        make_reader, db_path, data, expected, 'important', same_last_updated
    )


def _test_modified_copying(
    make_reader, db_path, data, expected, name, same_last_updated
):
    reader = make_reader(db_path)
    reader._parser = parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    reader.add_feed(feed)

    same_last_updated = False

    if not same_last_updated:
        # if .last_updated differs,
        # the entry with the most recent .last_updated remains

        for day_i, (id, *_) in enumerate(data, 1):
            reader._now = lambda: naive_datetime(2010, 1, day_i)
            # updated doesn't matter, this should never make the test fail
            updated = datetime(2010, 1, randrange(1, 30))
            parser.entry(1, id, updated, title='title', summary='summary')
            reader.update_feeds()

    else:
        # if .last_updated is the same for all entries,
        # the order from get_entries(sort='recent') is preserved;
        # in this case, the entry with the most recent .updated remains

        reader._now = lambda: naive_datetime(2010, 1, 1)
        for day_i, (id, *_) in enumerate(data, 1):
            parser.entry(
                1, id, datetime(2010, 1, day_i), title='title', summary='summary'
            )
        reader.update_feeds()

    reader._now: lambda: naive_datetime(2011, 1, 1)

    # the entry with the highest id is the last one
    for id, flag, modified in data:
        getattr(reader, f'set_entry_{name}')(('1', f'1, {id}'), flag, modified)

    reader = make_reader(db_path, plugins=['reader.entry_dedupe'])
    reader._parser = parser
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
def test_entry_tags_copying(make_reader, db_path, tags):
    *old_tags, new_tags, expected_tags = tags

    reader = make_reader(db_path)
    reader._parser = parser = Parser()
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
    reader._parser = parser
    reader.set_tag(feed, '.reader.dedupe.once')
    reader.update_feeds()

    assert not list(reader.get_tag_keys(one))
    assert not list(reader.get_tag_keys(two))
    assert dict(reader.get_tags(three)) == expected_tags
