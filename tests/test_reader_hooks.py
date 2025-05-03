from functools import partial

import pytest

from fakeparser import Parser
from reader import EntryUpdateStatus
from reader import ParseError
from reader import SingleUpdateHookError
from reader import UpdateHookErrorGroup
from reader._types import EntryData
from test_reader_private import CustomParser
from test_reader_private import CustomRetriever
from utils import utc_datetime as datetime


def test_after_entry_update_hooks(reader, parser):
    plugin_calls = []

    def first_plugin(r, e, s):
        assert r is reader
        plugin_calls.append((first_plugin, e, s))

    def second_plugin(r, e, s):
        assert r is reader
        plugin_calls.append((second_plugin, e, s))

    feed = parser.feed(1, datetime(2010, 1, 1))
    one = parser.entry(1, 1, datetime(2010, 1, 1))
    reader.add_feed(feed.url)
    reader.after_entry_update_hooks.append(first_plugin)
    reader.update_feeds()
    assert plugin_calls == [(first_plugin, one, EntryUpdateStatus.NEW)]
    assert {e.id for e in reader.get_entries()} == {'1, 1'}

    plugin_calls[:] = []

    feed = parser.feed(1, datetime(2010, 1, 2))
    one = parser.entry(1, 1, datetime(2010, 1, 2))
    two = parser.entry(1, 2, datetime(2010, 1, 2))
    reader.after_entry_update_hooks.append(second_plugin)
    reader.update_feeds()
    assert plugin_calls == [
        (first_plugin, two, EntryUpdateStatus.NEW),
        (second_plugin, two, EntryUpdateStatus.NEW),
        (first_plugin, one, EntryUpdateStatus.MODIFIED),
        (second_plugin, one, EntryUpdateStatus.MODIFIED),
    ]
    assert {e.id for e in reader.get_entries()} == {'1, 1', '1, 2'}


@pytest.mark.parametrize(
    'exists, overwrite, status',
    [
        (False, False, EntryUpdateStatus.NEW),
        (False, True, EntryUpdateStatus.NEW),
        (True, True, EntryUpdateStatus.MODIFIED),
    ],
)
def test_after_entry_update_hooks_add_entry(reader, exists, overwrite, status):
    reader.add_feed('1')
    if exists:
        reader.add_entry(EntryData('1', '1, 1'))

    plugin_calls = []

    def first_plugin(r, e, s):
        assert r is reader
        plugin_calls.append((first_plugin, e, s))

    def second_plugin(r, e, s):
        assert r is reader
        plugin_calls.append((second_plugin, e, s))

    reader.after_entry_update_hooks.append(first_plugin)
    reader.after_entry_update_hooks.append(second_plugin)

    entry = EntryData('1', '1, 1', title='title')

    reader.add_entry(entry, overwrite=overwrite)

    assert plugin_calls == [
        (first_plugin, entry, status),
        (second_plugin, entry, status),
    ]


def test_feed_update_hooks(reader, parser):
    plugin_calls = []

    def before_plugin(r, f):
        assert r is reader
        plugin_calls.append((before_plugin, f))

    def first_plugin(r, f):
        assert r is reader
        plugin_calls.append((first_plugin, f))

    def second_plugin(r, f):
        assert r is reader
        plugin_calls.append((second_plugin, f))

    # TODO: these should all be different tests

    # base case
    one = parser.feed(1, datetime(2010, 1, 1))
    parser.entry(1, 1, datetime(2010, 1, 1))
    reader.add_feed(one)
    reader.after_feed_update_hooks.append(first_plugin)
    reader.before_feed_update_hooks.append(before_plugin)
    reader.update_feeds()
    assert plugin_calls == [(before_plugin, one.url), (first_plugin, one.url)]

    plugin_calls[:] = []

    # gets called if something changes
    parser.entry(1, 1, datetime(2010, 1, 2))
    reader.update_feeds()
    assert plugin_calls == [(before_plugin, one.url), (first_plugin, one.url)]

    plugin_calls[:] = []

    # gets called even if there was no change
    reader.update_feeds()
    assert plugin_calls == [(before_plugin, one.url), (first_plugin, one.url)]

    plugin_calls[:] = []

    # gets called even if the feed was not modified
    parser.not_modified()
    reader.update_feeds()
    assert plugin_calls == [(before_plugin, one.url), (first_plugin, one.url)]

    plugin_calls[:] = []

    # gets called even if there was an error
    parser.raise_exc()
    reader.update_feeds()
    assert plugin_calls == [(before_plugin, one.url), (first_plugin, one.url)]

    plugin_calls[:] = []

    # plugin order and feed order is maintained
    parser.reset_mode()
    two = parser.feed(2, datetime(2010, 1, 1))
    reader.add_feed(two)
    reader.after_feed_update_hooks.append(second_plugin)
    reader.update_feeds()
    assert plugin_calls == [
        (before_plugin, one.url),
        (first_plugin, one.url),
        (second_plugin, one.url),
        (before_plugin, two.url),
        (first_plugin, two.url),
        (second_plugin, two.url),
    ]

    plugin_calls[:] = []

    # update_feed() only runs hooks for that plugin
    reader.update_feed(one)
    assert plugin_calls == [
        (before_plugin, one.url),
        (first_plugin, one.url),
        (second_plugin, one.url),
    ]


def test_feeds_update_hooks(reader, parser):
    plugin_calls = []

    def before_feed_plugin(r, f):
        assert r is reader
        plugin_calls.append((before_feed_plugin, f))

    def after_feed_plugin(r, f):
        assert r is reader
        plugin_calls.append((after_feed_plugin, f))

    def before_feeds_plugin(r):
        assert r is reader
        plugin_calls.append((before_feeds_plugin,))

    def after_feeds_plugin(r):
        assert r is reader
        plugin_calls.append((after_feeds_plugin,))

    reader.before_feed_update_hooks.append(before_feed_plugin)
    reader.after_feed_update_hooks.append(after_feed_plugin)
    reader.before_feeds_update_hooks.append(before_feeds_plugin)
    reader.after_feeds_update_hooks.append(after_feeds_plugin)

    # TODO: these should all be different tests

    # no feeds
    reader.update_feeds()
    assert plugin_calls == [(before_feeds_plugin,), (after_feeds_plugin,)]

    plugin_calls[:] = []

    # two feeds + feed vs feeds order
    one = parser.feed(1, datetime(2010, 1, 1))
    two = parser.feed(2, datetime(2010, 1, 1))
    reader.add_feed(one)
    reader.add_feed(two)
    reader.update_feeds()
    assert plugin_calls[0] == (before_feeds_plugin,)
    assert plugin_calls[-1] == (after_feeds_plugin,)
    assert set(plugin_calls[1:-1]) == {
        (before_feed_plugin, one.url),
        (after_feed_plugin, one.url),
        (before_feed_plugin, two.url),
        (after_feed_plugin, two.url),
    }

    plugin_calls[:] = []

    # not called for update_feed()
    reader.update_feed(one)
    assert set(plugin_calls) == {
        (before_feed_plugin, one.url),
        (after_feed_plugin, one.url),
    }

    plugin_calls[:] = []

    # called even if there's an error
    parser.raise_exc()
    reader.update_feeds()
    assert plugin_calls[0] == (before_feeds_plugin,)
    assert plugin_calls[-1] == (after_feeds_plugin,)
    assert set(plugin_calls[1:-1]) == {
        (before_feed_plugin, one.url),
        (after_feed_plugin, one.url),
        (before_feed_plugin, two.url),
        (after_feed_plugin, two.url),
    }


HOOK_ORDER = [
    'before_feeds_update_hooks',
    'before_feed_update_hooks',
    'after_entry_update_hooks',
    'after_feed_update_hooks',
    'after_feeds_update_hooks',
]


def setup_failing_hook(reader, hook_name):
    hook_names = [hook_name] if isinstance(hook_name, str) else hook_name

    reader._parser = parser = Parser()
    for feed_id in 1, 2:
        reader.add_feed(parser.feed(feed_id))
        parser.entry(feed_id, 1)
        if feed_id == 1:
            parser.entry(feed_id, 2)

    def update_hook(exc, r, obj=None, *_):
        feed_url = getattr(obj, 'feed_url', obj)
        if not feed_url or feed_url == '1':
            raise exc

    exc = RuntimeError('error')
    hook = partial(update_hook, exc)
    for hook_name in hook_names:
        getattr(reader, hook_name).append(hook)

    other_calls = []

    def other_hook(name, r, obj=None, *_):
        resource_id = getattr(obj, 'resource_id', obj)
        other_calls.append((name, resource_id))

    for name in HOOK_ORDER:
        getattr(reader, name).append(partial(other_hook, name))

    return exc, hook, other_calls


def hook_error_as_tree(error):
    if isinstance(error, SingleUpdateHookError):
        return error.when, error.hook, error.resource_id, error.__cause__
    if isinstance(error, UpdateHookErrorGroup):
        return [hook_error_as_tree(e) for e in error.exceptions]
    assert False, error


OTHER_CALLS_ONE = [
    ('before_feed_update_hooks', '1'),
    ('after_entry_update_hooks', ('1', '1, 2')),
    ('after_entry_update_hooks', ('1', '1, 1')),
    ('after_feed_update_hooks', '1'),
]

OTHER_CALLS_TWO = [
    ('before_feed_update_hooks', '2'),
    ('after_entry_update_hooks', ('2', '2, 1')),
    ('after_feed_update_hooks', '2'),
]

OTHER_CALLS_ENDS = (
    [('before_feeds_update_hooks', None)],
    [('after_feeds_update_hooks', None)],
)


def check_sublists(actual, *sublists, ends=None):
    """Check if all the sublists elements are present in actual.

    The sublists elements may be interleaved in actual,
    but they must be in actual order.

    If ends is given, check actual starts with ends[0] and ends with ends[1].

    sublists and ends must fully cover actual (no extra elements).

    """
    actual = list(actual)

    if ends:
        start, end = ends
        assert actual[: len(start)] == start
        assert actual[-len(end) :] == end
        actual = actual[len(start) : -len(end)]

    for sublist in sublists:
        indexes = [actual.index(e) for e in sublist]
        indexes.sort()
        found = [actual[i] for i in indexes]
        assert found == sublist
        actual = [e for i, e in enumerate(actual) if i not in indexes]

    assert not actual, "some elements left over"


def test_before_feeds_update_error(reader, update_feeds_iter):
    if 'simulated' in update_feeds_iter.__name__:
        pytest.skip("does not apply")

    exc, hook, other_calls = setup_failing_hook(reader, 'before_feeds_update_hooks')

    with pytest.raises(SingleUpdateHookError) as exc_info:
        rv = []
        for result in update_feeds_iter(reader):
            rv.append(result)

    assert not rv

    error = exc_info.value
    assert hook_error_as_tree(error) == ('before_feeds_update', hook, None, exc)

    assert {e.id for e in reader.get_entries()} == set()

    assert other_calls == []


def test_before_feed_update_error(reader, update_feeds_iter):
    exc, hook, other_calls = setup_failing_hook(reader, 'before_feed_update_hooks')

    rv = {int(r.url): r for r in update_feeds_iter(reader)}

    one = rv.pop(1)
    assert len(rv) == 1
    assert all([r.updated_feed for r in rv.values()])

    error = one.error
    assert hook_error_as_tree(error) == ('before_feed_update', hook, ('1',), exc)

    assert {e.id for e in reader.get_entries()} == {'2, 1'}

    # these may change (e.g. if we don't run after_* hooks after ParseError)
    simulated = 'simulated' in update_feeds_iter.__name__
    ends = OTHER_CALLS_ENDS if not simulated else None
    check_sublists(other_calls, OTHER_CALLS_TWO, ends=ends)


def test_after_entry_update_error(reader, update_feeds_iter):
    exc, hook, other_calls = setup_failing_hook(reader, 'after_entry_update_hooks')

    rv = {int(r.url): r for r in update_feeds_iter(reader)}

    one = rv.pop(1)
    assert len(rv) == 1
    assert all([r.updated_feed for r in rv.values()])

    errors = one.error
    assert hook_error_as_tree(errors) == [
        ('after_entry_update', hook, ('1', '1, 2'), exc),
        ('after_entry_update', hook, ('1', '1, 1'), exc),
    ]

    assert {e.id for e in reader.get_entries()} == {'1, 1', '1, 2', '2, 1'}

    # these may change (e.g. if we don't run after_* hooks after ParseError)
    simulated = 'simulated' in update_feeds_iter.__name__
    ends = OTHER_CALLS_ENDS if not simulated else None
    check_sublists(other_calls, OTHER_CALLS_ONE, OTHER_CALLS_TWO, ends=ends)


def test_after_feed_update_error(reader, update_feeds_iter):
    exc, hook, other_calls = setup_failing_hook(reader, 'after_feed_update_hooks')

    rv = {int(r.url): r for r in update_feeds_iter(reader)}

    one = rv.pop(1)
    assert len(rv) == 1
    assert all([r.updated_feed for r in rv.values()])

    errors = one.error
    assert hook_error_as_tree(errors) == [('after_feed_update', hook, ('1',), exc)]

    assert {e.id for e in reader.get_entries()} == {'1, 1', '1, 2', '2, 1'}

    # these may change (e.g. if we don't run after_* hooks after ParseError)
    simulated = 'simulated' in update_feeds_iter.__name__
    ends = OTHER_CALLS_ENDS if not simulated else None
    check_sublists(other_calls, OTHER_CALLS_ONE, OTHER_CALLS_TWO, ends=ends)


def test_after_feeds_update_error(reader, update_feeds_iter):
    if 'simulated' in update_feeds_iter.__name__:
        pytest.skip("does not apply")

    exc, hook, other_calls = setup_failing_hook(reader, 'after_feeds_update_hooks')

    with pytest.raises(UpdateHookErrorGroup) as exc_info:
        rv = []
        for result in update_feeds_iter(reader):
            rv.append(result)

    assert len(rv) == 2
    assert all([r.updated_feed for r in rv])

    errors = exc_info.value
    assert hook_error_as_tree(errors) == [
        ('after_feeds_update', hook, None, exc),
    ]

    assert {e.id for e in reader.get_entries()} == {'1, 1', '1, 2', '2, 1'}

    check_sublists(other_calls, OTHER_CALLS_ONE, OTHER_CALLS_TWO, ends=OTHER_CALLS_ENDS)


def test_update_feeds_before_feeds_update_error(reader):
    exc, hook, other_calls = setup_failing_hook(reader, 'before_feeds_update_hooks')

    with pytest.raises(SingleUpdateHookError) as exc_info:
        reader.update_feeds()

    error = exc_info.value
    assert hook_error_as_tree(error) == ('before_feeds_update', hook, None, exc)

    assert {e.id for e in reader.get_entries()} == set()

    assert other_calls == []


def test_update_feeds_before_feed_update_error(reader):
    exc, hook, other_calls = setup_failing_hook(reader, 'before_feed_update_hooks')

    with pytest.raises(UpdateHookErrorGroup) as exc_info:
        reader.update_feeds()

    error = exc_info.value
    assert hook_error_as_tree(error) == [('before_feed_update', hook, ('1',), exc)]

    assert {e.id for e in reader.get_entries()} == {'2, 1'}

    check_sublists(other_calls, OTHER_CALLS_TWO, ends=OTHER_CALLS_ENDS)


def test_update_feeds_other_error(reader):
    exc, hook, other_calls = setup_failing_hook(
        reader,
        [
            'after_entry_update_hooks',
            'after_feed_update_hooks',
            'after_feeds_update_hooks',
        ],
    )

    with pytest.raises(UpdateHookErrorGroup) as exc_info:
        reader.update_feeds()

    error = exc_info.value
    assert hook_error_as_tree(error) == [
        [
            ('after_entry_update', hook, ('1', '1, 2'), exc),
            ('after_entry_update', hook, ('1', '1, 1'), exc),
            ('after_feed_update', hook, ('1',), exc),
        ],
        [
            ('after_feeds_update', hook, None, exc),
        ],
    ]

    assert {e.id for e in reader.get_entries()} == {'1, 1', '1, 2', '2, 1'}

    check_sublists(other_calls, OTHER_CALLS_ONE, OTHER_CALLS_TWO, ends=OTHER_CALLS_ENDS)


@pytest.mark.parametrize('hook_name', ['request_hooks', 'response_hooks'])
def test_session_hook_unexpected_exception(
    reader, data_dir, update_feeds_iter, requests_mock, hook_name
):
    for feed_id in 1, 2, 3:
        url = f'http://example.com/{feed_id}'
        requests_mock.get(
            url,
            text=data_dir.joinpath('full.atom').read_text(),
            headers={'content-type': 'application/atom+xml'},
        )
        reader.add_feed(url)

    exc = RuntimeError('error')

    def hook(session, obj, *_, **__):
        if '1' in obj.url:
            raise exc

    getattr(reader._parser.session_factory, hook_name).append(hook)

    rv = {int(r.url.rpartition('/')[2]): r for r in update_feeds_iter(reader)}

    assert rv[1].error.__cause__ is exc
    assert isinstance(rv[1].error, ParseError)
    assert rv[1].error.__cause__ is exc
    assert rv[2].updated_feed
    assert rv[3].updated_feed
