import random
import re

import pytest

from reader import Content
from reader import Entry
from reader.plugins import entry_dedupe
from reader.plugins.entry_dedupe import common_prefixes
from reader.plugins.entry_dedupe import group_by
from reader.plugins.entry_dedupe import init_reader
from reader.plugins.entry_dedupe import is_duplicate
from reader.plugins.entry_dedupe import is_duplicate_entry
from reader.plugins.entry_dedupe import merge_flags
from reader.plugins.entry_dedupe import merge_tags
from reader.plugins.entry_dedupe import ngrams
from reader.plugins.entry_dedupe import tokenize_content
from reader.plugins.entry_dedupe import tokenize_title
from utils import parametrize_dict
from utils import utc_datetime as datetime


@pytest.fixture
def reader(make_reader, request):
    plugins = []
    if 'with_plugin' in request.fixturenames:
        plugins.append('reader.entry_dedupe')
    return make_reader(':memory:', plugins=plugins)


@pytest.fixture
def with_plugin():
    """Tell reader to use the plugin from the beginning."""


def test_only_duplicates_are_deleted(reader, parser, monkeypatch):
    # detailed/fuzzy content matching tested in test_is_duplicate*

    reader.add_feed(parser.feed(1))

    # increase this slightly to allow for published(-day) in the same test
    monkeypatch.setattr(entry_dedupe, 'MAX_GROUP_SIZE', entry_dedupe.MAX_GROUP_SIZE + 1)

    common_attrs = dict(
        updated=datetime(2010, 1, 1, 2, 3, 4),
        title='title',
        link='link',
    )

    parser.entry(1, 'different', **common_attrs, summary='another')
    parser.entry(1, 'title', title='Title', summary='value')
    parser.entry(1, 'title-x', summary='value')
    parser.entry(1, 'link', link='link', summary='value')
    parser.entry(1, 'link-x', link='link')
    parser.entry(1, 'published', published=datetime(2010, 1, 1, 2, 3), summary='value')
    parser.entry(1, 'published-x', published=datetime(2010, 1, 1, 2, 3))
    parser.entry(1, 'published-day', datetime(2010, 1, 1), summary='value')
    parser.entry(1, 'published-day-x', datetime(2010, 1, 1))
    parser.entry(1, 'prefix', title='prefix-title', summary='value')
    parser.entry(1, 'prefix-x', title='prefix-x', summary='value')
    parser.entry(1, 'prefix-xx', title='prefix-xx')
    parser.entry(1, 'prefix-xxx', title='prefix-xxx')
    parser.entry(1, 'title-similarity', title='TilE', summary='value')
    parser.entry(1, 'title-similarity-x', title='tale', summary='value')

    reader.update_feeds()

    init_reader(reader)

    parser.entry(1, 'entry', **common_attrs, summary='value')
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {
        'different',
        'title-x',
        'link-x',
        'published-x',
        'published-day-x',
        'prefix-x',
        'prefix-xx',
        'prefix-xxx',
        'title-similarity-x',
        'entry',
    }


def test_mass_duplication_doesnt_use_all_groupers(reader, parser, caplog):
    reader.add_feed(parser.feed(1))

    for i in range(4):
        parser.entry(1, f'{i}-old', datetime(2010, 1, 1), title=str(i), summary=str(i))
    reader.update_feeds()

    init_reader(reader)
    caplog.set_level('DEBUG')

    for i in range(4):
        parser.entry(1, f'{i}-new', datetime(2010, 1, 2), title=str(i), summary=str(i))
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {'0-new', '1-new', '2-new', '3-new'}

    assert 'title_grouper' in caplog.text
    assert 'link_grouper' not in caplog.text
    assert 'no new entries remaining' in caplog.text


def test_duplicates_in_another_feed_are_ignored(reader, with_plugin, parser):
    reader.add_feed(parser.feed(1))
    reader.add_feed(parser.feed(2))

    yesterday = datetime(2010, 1, 1)
    parser.entry(1, 1, yesterday, title='title', summary='value')
    reader.update_feeds()

    today = datetime(2010, 1, 2)
    parser.entry(2, 1, today, title='title', summary='value')
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {'1, 1', '2, 1'}


def test_duplicates_change_during_update(reader, with_plugin, parser):
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


@parametrize_dict(
    'tags, expected',
    {
        'once': (['once'], {'entry', 'title-only', 'link-only'}),
        'once.title': (['once.title'], {'entry', 'link-and-summary', 'link-only'}),
        'both': (['once', 'once.title'], {'entry', 'title-only', 'link-only'}),
    },
)
def test_dedupe_once(reader, parser, tags, expected):
    feed = parser.feed(1)
    reader.add_feed(feed)
    reader.set_tag(feed, 'unrelated')

    parser.entry(1, 'title-and-summary', title='title', summary='value')
    parser.entry(1, 'title-only', title='title')
    parser.entry(1, 'link-and-summary', link='link', summary='value')
    parser.entry(1, 'link-only', link='link')

    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    parser.entry(1, 'entry', title='title', link='link', summary='value')
    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    init_reader(reader)

    for tag in tags:
        reader.set_tag(feed, f".reader.dedupe.{tag}")
    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == expected
    assert set(reader.get_tag_keys(feed)) == {'unrelated'}


@pytest.mark.parametrize(
    'tag, expected',
    [(None, 'new-pub'), ('once', 'new-last-upd'), ('once.title', 'new-last-upd')],
)
def test_dedupe_once_order(reader, parser, tag, expected):
    feed = parser.feed(1)
    reader.add_feed(feed)

    common_attrs = dict(title='title', summary='value')

    parser.entry(1, 'old', datetime(2010, 1, 1), **common_attrs)
    parser.entry(1, 'new-pub', datetime(2010, 1, 3), **common_attrs)
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    parser.entry(1, 'new-last-upd', datetime(2010, 1, 1), **common_attrs)
    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    if not tag:
        init_reader(reader)

    parser.entry(1, 'entry', datetime(2010, 1, 2), **common_attrs)
    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    if tag:
        init_reader(reader)
        reader.set_tag(feed, f".reader.dedupe.{tag}")
        reader.update_feeds()

    assert {e.id for e in reader.get_entries()} == {expected}


def test_dedupe_once_title_uses_only_title_grouper(reader, parser, caplog):
    feed = parser.feed(1)
    reader.add_feed(feed)
    parser.entry(1, 1)
    reader.update_feeds()

    init_reader(reader)
    caplog.set_level('DEBUG')

    reader.set_tag(feed, ".reader.dedupe.once.title")
    reader.update_feeds()

    assert 'title_grouper' in caplog.text
    assert 'link_grouper' not in caplog.text


@pytest.mark.parametrize('read', [False, True])
@pytest.mark.parametrize('modified', [None, datetime(2010, 1, 1, 1)])
def test_read(reader, with_plugin, parser, read, modified):
    # multiple duplicates / modified priority tested in test_merge_flags

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


@pytest.mark.parametrize('important', [False, None, True])
@pytest.mark.parametrize('modified', [None, datetime(2010, 1, 1, 1)])
def test_important(reader, with_plugin, parser, important, modified):
    # multiple duplicates / modified priority tested in test_merge_flags

    reader.add_feed(parser.feed(1))

    yesterday = datetime(2010, 1, 1)
    one = parser.entry(1, 1, yesterday, title='title', summary='value')
    reader.update_feeds()

    reader.set_entry_important(one, important, modified)

    today = datetime(2010, 1, 2)
    two = parser.entry(1, 2, today, title='title', summary='value')
    reader.update_feeds()

    two = reader.get_entry(two)
    assert two.important == important
    assert two.important_modified == modified


def test_tags(reader, parser):
    feed = parser.feed(1)
    reader.add_feed(feed)

    one = parser.entry(1, 1, datetime(2010, 1, 2), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    two = parser.entry(1, 2, datetime(2010, 1, 1), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    reader.set_tag(one, 'just', 'one')
    reader.set_tag(one, 'same', 'value')
    reader.set_tag(two, 'same', 'value')
    reader.set_tag(one, 'different', 'one')
    reader.set_tag(two, 'different', 'two')

    init_reader(reader)

    three = parser.entry(1, 3, datetime(2010, 1, 3), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    assert dict(reader.get_tags(three)) == {
        'just': 'one',
        'same': 'value',
        'different': 'one',
        '.reader.duplicate.1.of.different': 'two',
    }


def test_tags_dedupe_once(reader, parser):
    feed = parser.feed(1)
    reader.add_feed(feed)

    one = parser.entry(1, 1, datetime(2010, 1, 2), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 1)
    reader.update_feeds()

    two = parser.entry(1, 2, datetime(2010, 1, 1), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 2)
    reader.update_feeds()

    reader.set_tag(one, 'just', 'one')
    reader.set_tag(one, 'same', 'value')
    reader.set_tag(two, 'same', 'value')
    reader.set_tag(one, 'different', 'one')
    reader.set_tag(two, 'different', 'two')

    three = parser.entry(1, 3, datetime(2010, 1, 3), title='title', summary='value')
    reader._now = lambda: datetime(2010, 1, 3)
    reader.update_feeds()

    reader.set_tag(three, 'same', 'value')
    reader.set_tag(three, 'different', 'three')
    reader.set_tag(three, 'only', 'three')

    init_reader(reader)
    reader.set_tag(feed, '.reader.dedupe.once')
    reader.update_feeds()

    assert dict(reader.get_tags(three)) == {
        'just': 'one',
        'same': 'value',
        'different': 'three',
        # note the order differs from test_tags
        '.reader.duplicate.1.of.different': 'two',
        '.reader.duplicate.2.of.different': 'one',
        'only': 'three',
    }


def make_entry(title=None, summary=None, content=None):
    entry = Entry('id', None, title=title, summary=summary)
    if content:
        entry = entry._replace(content=[Content(*content)])
    return entry


IS_DUPLICATE_ENTRY_DATA = [
    (make_entry(), make_entry(), False),
    (make_entry(title='title'), make_entry(title='title'), False),
    (make_entry(summary='summary'), make_entry(summary='summary'), True),
    (
        make_entry(content=('value', 'text/html')),
        make_entry(content=('value', 'text/html')),
        True,
    ),
    (
        make_entry(title='title', summary='summary'),
        make_entry(title='title', summary='summary'),
        True,
    ),
    (
        make_entry(title='title', summary='summary'),
        make_entry(title='other', summary='summary'),
        True,
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
        True,
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
    # TODO: test fuzzy matching (just one test)
    # TODO: test normalization
]


@pytest.mark.parametrize('one, two, result', IS_DUPLICATE_ENTRY_DATA)
def test_is_duplicate_entry(one, two, result):
    assert bool(is_duplicate_entry(one, two)) is bool(result)


# ([duplicates, ..., entry], expected), ...
MERGE_FLAGS_DATA = [
    # no change
    ([(True, None)], None),
    ([(False, None), (False, 2)], None),
    ([(None, None), (True, 2)], None),
    # read beats not read
    ([(True, None), (False, None)], (True, None)),
    # important beats not set
    ([(True, None), (None, None)], (True, None)),
    # unimportant beats not set
    ([(False, None), (None, None)], (False, None)),
    # none read, earliest modified wins
    ([(False, None), (False, 2), (False, 3)], (False, 2)),
    # none set, earliest modified wins
    ([(None, None), (None, 2), (None, 3)], (None, 2)),
    # some read, earliest read modified wins
    ([(True, None), (False, 2), (True, 3), (True, 4), (None, 5)], (True, 3)),
    # some not set + unimportant, earliest unimportant modified wins
    ([(None, None), (False, 2), (None, 3), (False, 4)], (False, 2)),
]


@pytest.mark.parametrize('flags, expected', MERGE_FLAGS_DATA)
def test_merge_flags(flags, expected):
    def from_days(flag):
        if not flag:
            return None
        value, days = flag
        return value, datetime(2010, 1, days) if days is not None else None

    *duplicates, entry = map(from_days, flags)

    # duplicate order does not matter
    random.shuffle(duplicates)

    assert merge_flags(entry, duplicates) == from_days(expected)


# TODO: test order remains stable if last_updated is the same


COMPLEX_TAGS = {'tag': {'string': [10, True]}}

# ([duplicates, ..., entry], expected), ...
MERGE_TAGS_DATA = [
    # no duplicate entries
    ([{}], {}),
    ([{'tag': None}], {}),
    # duplicate entry with no tags
    ([{}, {}], {}),
    # tag doesn't exist
    ([{'tag': None}, {}], {'tag': None}),
    ([{'tag': 'one'}, {}], {'tag': 'one'}),
    # different tags are merged
    ([{'one': 1}, {'two': 2}, {'three': 3}], {'one': 1, 'two': 2}),
    # tag exists with the same value
    ([{'tag': None}, {'tag': None}], {}),
    # tag doesn't exist, multiple duplicate entries with the same value
    ([{'tag': None}, {'tag': None}, {}], {'tag': None}),
    ([COMPLEX_TAGS, COMPLEX_TAGS, {}], COMPLEX_TAGS),
    # tag doesn't exist, multiple duplicate entries with different values
    ([{'tag': 1}, {'tag': 2}, {}], {'tag': 1, '.duplicate.1.of.tag': 2}),
    # tag exists, multiple duplicate entries with different values
    (
        [{'tag': 1}, {'tag': 2}, {'tag': 3}],
        {'.duplicate.1.of.tag': 1, '.duplicate.2.of.tag': 2},
    ),
    # existing duplicate tag remains unchanged, no duplicate entries
    ([{'.duplicate.1.of.tag': 1}], {}),
    # existing duplicate tag remains unchanged, duplicate entry
    ([{'tag': 1}, {'.duplicate.1.of.tag': 2}], {'tag': 1}),
    # existing duplicate tag remains unchanged, even if out of order
    ([{'tag': 1}, {'.duplicate.10.of.tag': 2}], {'tag': 1}),
    # existing duplicate tag is skipped
    (
        [
            {'.duplicate.1.of.tag': 1},
            {'.duplicate.1.of.tag': 2},
            {'.duplicate.1.of.tag': 3},
        ],
        {'tag': 1, '.duplicate.2.of.tag': 2},
    ),
    # out of order duplicate tags get renumbered
    (
        [
            {'.duplicate.20.of.tag': 1, '.duplicate.10.of.tag': 2},
            {'.duplicate.10.of.tag': 3},
            {'tag': 4},
        ],
        {
            '.duplicate.1.of.tag': 1,
            '.duplicate.2.of.tag': 2,
            '.duplicate.3.of.tag': 3,
        },
    ),
    # duplicates have .dedupe set
    ([{'.dedupe': None}, {'.dedupe': 2}, {}], {}),
]


@pytest.mark.parametrize('tags, expected', MERGE_TAGS_DATA)
def test_merge_tags(reader, parser, tags, expected):
    *duplicates, entry = tags

    def make_reserved(n):
        return '.' + n

    assert dict(merge_tags(make_reserved, entry, duplicates)) == expected


# TODO: with_maybe_published_or_updated
def test_recent_sort_copying(reader, parser):
    reader.add_feed(parser.feed(1))

    parser.entry(1, 1, title='title', summary='summary')
    reader._now = lambda: datetime(2010, 1, 10)
    reader.update_feeds()

    parser.entry(1, 2, title='title', summary='summary')
    parser.entry(1, 3, title='other')
    reader._now = lambda: datetime(2010, 1, 20)
    reader.update_feeds()

    init_reader(reader)

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
    reader, with_plugin, parser, update_after_one, with_dates, expected_id
):
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


def with_edits(text, edits, end_at=None):
    if end_at:
        text = re.search(rf"(?s).*?{end_at}", text)[0]
    edited = text
    for edit in edits:
        edited = edited.replace(*edit)
    return text, edited


TEXT = """\
So, you're doing some I/O bound stuff, in parallel.

Maybe you're scraping some websites – a lot of websites.

Maybe you're updating or deleting millions of DynamoDB items.

You've got your [ThreadPoolExecutor],
you've increased the number of threads and tuned connection limits...
but after some point, **it's just not getting any faster**.
You look at your Python process,
and you see CPU utilization hovers above 100%.

You *could* split the work into batches
and have a [ProcessPoolExecutor]
run your original code in separate processes.
But that requires yet more code, and a bunch of changes, which is no fun.
And maybe your input is not that easy to split into batches.

If only we had an executor that
**worked seamlessly across processes and threads**.

Well, you're in luck, since that's exactly what we're building today!

And even better, in a couple years you won't even need it anymore.

---

**asyncio-thread-runner** allows you to run async code from sync code.

This is useful when you're doing some sync stuff, but:

* you also need to do some async stuff, **without** making **everything async**
* maybe the sync stuff is an existing application
* maybe you still want to use your favorite sync library
* or maybe you need just a little async, without having to pay the full price

Features:

* unlike [asyncio.run()], it provides a **long-lived event loop**
* unlike [asyncio.Runner], it runs in a dedicated thread, and you can use it from **multiple threads**
* it allows you to use **async context managers** and **iterables** from sync code
* check out [this article](https://death.andgravity.com/asyncio-bridge) for why these are useful

"""
EDITS = [
    ("you're", "youre"),
    ("I/O bound", "IO-bound"),
    ("parallel", "paralel"),
    ("Maybe", "And", 1),
    ("a lot", "lots"),
    ("PoolExecutor", " Pool Executor"),
    ("work", "input"),
    ("you won't even need it anymore", ""),
]
EXTRA_EDITS = EDITS + [
    ("So", "Soo"),
    ("stuff", "thing"),
    ("millions", "billions"),
    ("across processes and threads", ""),
]


IS_DUPLICATE_DATA = [
    ('one two three four', 'one two three four', True),
    ('one two three four', 'one two thre four', True),
    ('one two three four', 'one two three five', False),
    ('hello', 'helo', True),
    ('hello', 'helio', False),
    (*with_edits(TEXT, EDITS, "you're"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "you're"), False),
    (*with_edits(TEXT, EDITS, "parallel"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "parallel"), False),
    (*with_edits(TEXT, EDITS, "items"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "items"), False),
    (*with_edits(TEXT, EDITS, "anymore"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "anymore"), False),
    (*with_edits(TEXT, EDITS, "$"), True),
    (*with_edits(TEXT, EXTRA_EDITS, "$"), False),
]


def long_ids(s):
    if isinstance(s, str):
        if len(s) > 20:
            return s[:6] + '...' + s[-10:]


@pytest.mark.parametrize('one, two, expected', IS_DUPLICATE_DATA, ids=long_ids)
def test_is_duplicate(one, two, expected):
    actual = is_duplicate(tokenize_content(one), tokenize_content(two))
    assert actual == expected


@pytest.mark.parametrize(
    'seq, n, pad, expected',
    [
        ([1, 2, 3], 2, False, [(1, 2), (2, 3)]),
        ([1, 2], 2, False, [(1, 2)]),
        ([1], 2, False, []),
        ([], 2, False, []),
        ([1, 2], 2, True, [(None, 1), (1, 2), (2, None)]),
        ([1], 2, True, [(None, 1), (1, None)]),
        ([], 2, True, [(None, None)]),
    ],
)
def test_ngrams(seq, n, pad, expected):
    assert list(ngrams(seq, n, pad)) == expected


def test_common_prefixes():
    text = """\
        uncommon

        common one
        common two

        tiny prefix
        tiny is skipped

        subprefix is used
        subprefix is too
        subprefix if
        subprefix significant

        shortest xx wins
        shortest xx if
        shortest yy drop-off
        shortest yy is
        shortest zz too
        shortest zz sharp

        too xx but
        too xx not
        too yy if
        too yy it's
        too zz too
        too zz short

        duplicate counted just once
        duplicate counted just once

        but counted once
        but counted once
        but counted

    """
    documents = [tuple(l.split()) for l in text.splitlines()]
    assert set(common_prefixes(documents, min_df=2)) == {
        ('common',),
        ('subprefix', 'is'),
        ('subprefix',),
        ('shortest',),
        ('too', 'xx'),
        ('too', 'yy'),
        ('too', 'zz'),
        ('but', 'counted'),
    }


@pytest.mark.parametrize(
    'items, only_items, expected',
    [
        ('abc', 'a', [['a']]),
        ('aAb', 'a', [['a', 'A']]),
        ('abc', '', []),
    ],
)
def test_group_by(items, only_items, expected):
    assert list(group_by(str.upper, items, only_items)) == expected
