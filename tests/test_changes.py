import pytest

from fakeparser import Parser
from reader import Content
from reader import StorageError
from reader._types import Action
from reader._types import Change
from reader.exceptions import ChangeTrackingNotEnabledError


@pytest.fixture
def reader(reader, parser):
    feed = parser.feed('1', title='one')
    parser.entry('1', 'a', title='aaa')
    reader.add_feed(feed)

    def randomblob(n):
        randomblob.index += 1
        return f'seq{randomblob.index}'.encode()

    randomblob.index = 0

    def patch_randomblob():
        reader._storage.factory().create_function('randomblob', 1, randomblob)
        # reader._storage.factory().create_function('print', -1, print)

    reader.patch_randomblob = patch_randomblob

    return reader


@pytest.fixture
def storage(reader):
    return reader._storage


def get_entries(reader):
    return {(e.feed_url, e.id, e._sequence) for e in reader.get_entries()}


def test_disabled(reader, storage):
    reader.update_feeds()

    check_disabled(reader)

    storage.changes.enable()
    storage.changes.disable()

    check_disabled(reader)


def check_disabled(reader):
    storage = reader._storage

    assert get_entries(reader) == {('1', 'a', None)}

    with pytest.raises(ChangeTrackingNotEnabledError) as excinfo:
        storage.changes.get()
    with pytest.raises(ChangeTrackingNotEnabledError) as excinfo:
        storage.changes.done([Change(Action.INSERT, b'seq1', ('1', 'a'))])

    # should be a no-op
    storage.changes.disable()


def test_enable_empty(reader, storage):
    storage.changes.enable()
    # should be a no-op
    storage.changes.enable()

    assert storage.changes.get() == []


def test_enable_existing_entry(reader, storage):
    reader.patch_randomblob()
    reader.update_feeds()

    storage.changes.enable()
    # should be a no-op
    storage.changes.enable()

    assert get_entries(reader) == {('1', 'a', b'seq1')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.INSERT, b'seq1', ('1', 'a')),
    ]


def test_new_entry(reader, storage):
    reader.patch_randomblob()

    # make sure only the entry changes, not the feed (see test_new_feed below)
    reader.update_feeds()
    storage.delete_entries([('1', 'a')])

    storage.changes.enable()
    reader.update_feeds()

    assert get_entries(reader) == {('1', 'a', b'seq1')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.INSERT, b'seq1', ('1', 'a')),
    ]


def test_new_feed(reader, storage):
    reader.patch_randomblob()
    storage.changes.enable()
    reader.update_feeds()

    # sequence changes twice because both the entry and the feed change;
    # this is an implementation detail (brittle),
    # the outcome of test_new_entry would be acceptable too

    assert get_entries(reader) == {('1', 'a', b'seq2')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.DELETE, b'seq1', ('1', 'a')),
        Change(Action.INSERT, b'seq2', ('1', 'a')),
    ]


def set_entry_title(reader, value):
    reader._parser.entry('1', 'a', title=value)
    reader.update_feeds()


def set_entry_summary(reader, value):
    reader._parser.entry('1', 'a', title=None, summary=value)
    reader.update_feeds()


def set_entry_content(reader, value):
    content = []
    if value is not None:
        content.append(Content(value))
    reader._parser.entry('1', 'a', title=None, content=content)
    reader.update_feeds()


def set_feed_title(reader, value):
    reader._parser.feed('1', title=value)
    reader.update_feeds()


def set_feed_user_title(reader, value):
    reader.set_feed_user_title('1', value)


@pytest.mark.parametrize('clear', [False, True])
@pytest.mark.parametrize(
    'do_change',
    [
        set_entry_title,
        set_entry_summary,
        set_entry_content,
        set_feed_title,
        set_feed_user_title,
    ],
)
def test_update_one_field(reader, parser, storage, clear, do_change):
    reader.patch_randomblob()

    # all fields start with None
    parser.feed('1', title=None)
    parser.entry('1', 'a', title=None)
    reader.update_feeds()

    storage.changes.enable()
    storage.changes.done(storage.changes.get())

    # None -> None => no change
    do_change(reader, None)
    assert storage.changes.get() == []

    # None -> one => change
    do_change(reader, 'one')
    assert get_entries(reader) == {('1', 'a', b'seq2')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.DELETE, b'seq1', ('1', 'a')),
        Change(Action.INSERT, b'seq2', ('1', 'a')),
    ]
    if clear:
        storage.changes.done(storage.changes.get())
        old_changes = []
    else:
        old_changes = changes

    # one -> one => no change
    do_change(reader, 'one')
    assert get_entries(reader) == {('1', 'a', b'seq2')}
    assert storage.changes.get() == old_changes

    # one -> two => change
    do_change(reader, 'two')
    assert get_entries(reader) == {('1', 'a', b'seq3')}
    changes = storage.changes.get()
    assert changes == old_changes[:-1] + [
        Change(Action.DELETE, b'seq2', ('1', 'a')),
        Change(Action.INSERT, b'seq3', ('1', 'a')),
    ]
    if clear:
        storage.changes.done(storage.changes.get())
        old_changes = []
    else:
        old_changes = changes

    # two -> None => change
    do_change(reader, None)
    assert get_entries(reader) == {('1', 'a', b'seq4')}
    changes = storage.changes.get()
    assert changes == old_changes[:-1] + [
        Change(Action.DELETE, b'seq3', ('1', 'a')),
        Change(Action.INSERT, b'seq4', ('1', 'a')),
    ]


@pytest.mark.parametrize('do_change', [set_feed_title, set_feed_user_title])
def test_update_feed(reader, parser, storage, do_change):
    reader.patch_randomblob()
    parser.entry('1', 'b', title='bbb')
    reader.update_feeds()
    storage.changes.enable()

    # we don't care which entry gets which sequence (implementation detail),
    # we do care the correct type and number of changes happen overall

    assert {e.resource_id for e in reader.get_entries()} == {('1', 'a'), ('1', 'b')}
    assert {e._sequence for e in reader.get_entries()} == {b'seq1', b'seq2'}

    changes = storage.changes.get()
    assert {(c.action, c.sequence) for c in changes} == {
        (Action.INSERT, b'seq1'),
        (Action.INSERT, b'seq2'),
    }
    assert {(c.action, c.resource_id, c.tag_key) for c in changes} == {
        (Action.INSERT, ('1', 'a'), None),
        (Action.INSERT, ('1', 'b'), None),
    }

    assert [c.tag_key for c in changes] == [None, None]

    storage.changes.done(changes)
    do_change(reader, 'new')

    assert {e.resource_id for e in reader.get_entries()} == {('1', 'a'), ('1', 'b')}
    assert {e._sequence for e in reader.get_entries()} == {b'seq3', b'seq4'}

    changes = storage.changes.get()
    assert {(c.action, c.sequence) for c in changes} == {
        (Action.DELETE, b'seq1'),
        (Action.DELETE, b'seq2'),
        (Action.INSERT, b'seq3'),
        (Action.INSERT, b'seq4'),
    }
    assert {(c.action, c.resource_id, c.tag_key) for c in changes} == {
        (Action.DELETE, ('1', 'a'), None),
        (Action.DELETE, ('1', 'b'), None),
        (Action.INSERT, ('1', 'a'), None),
        (Action.INSERT, ('1', 'b'), None),
    }


def test_change_feed_url(reader, parser, storage):
    reader.patch_randomblob()
    reader.update_feeds()
    storage.changes.enable()
    storage.changes.done(storage.changes.get())

    assert get_entries(reader) == {('1', 'a', b'seq1')}

    reader.change_feed_url('1', '2')

    assert get_entries(reader) == {('2', 'a', b'seq2')}
    assert storage.changes.get() == [
        Change(Action.DELETE, b'seq1', ('1', 'a')),
        Change(Action.INSERT, b'seq2', ('2', 'a')),
    ]

    parser.feed('2', title='one')
    parser.entry('2', 'b', title='bbb')
    reader.update_feeds()

    assert get_entries(reader) == {('2', 'a', b'seq2'), ('2', 'b', b'seq3')}
    assert storage.changes.get() == [
        Change(Action.DELETE, b'seq1', ('1', 'a')),
        Change(Action.INSERT, b'seq2', ('2', 'a')),
        Change(Action.INSERT, b'seq3', ('2', 'b')),
    ]

    reader.change_feed_url('2', '1')
    assert get_entries(reader) == {('1', 'a', b'seq4'), ('1', 'b', b'seq5')}
    assert storage.changes.get() == [
        Change(Action.DELETE, b'seq1', ('1', 'a')),
        Change(Action.DELETE, b'seq2', ('2', 'a')),
        Change(Action.DELETE, b'seq3', ('2', 'b')),
        Change(Action.INSERT, b'seq4', ('1', 'a')),
        Change(Action.INSERT, b'seq5', ('1', 'b')),
    ]


@pytest.mark.parametrize('clear', [False, True])
def test_delete_feed_or_entry(reader, parser, storage, clear):
    reader.patch_randomblob()
    parser.entry('1', 'b', title='bbb')
    parser.entry('1', 'c', title='ccc')
    reader.update_feeds()
    storage.changes.enable()
    if clear:
        storage.changes.done(storage.changes.get())

    storage.delete_entries([('1', 'a')])

    changes = storage.changes.get()
    (change,) = (c for c in changes if c.resource_id == ('1', 'a'))
    assert change.action is Action.DELETE
    assert change.sequence in {b'seq1', b'seq2', b'seq3'}

    reader.delete_feed('1')

    changes = storage.changes.get()
    assert len(changes) == 3
    assert {c.sequence for c in changes} == {b'seq1', b'seq2', b'seq3'}
    assert {(c.action, c.resource_id, c.tag_key) for c in changes} == {
        (Action.DELETE, ('1', 'a'), None),
        (Action.DELETE, ('1', 'b'), None),
        (Action.DELETE, ('1', 'c'), None),
    }


def test_get_filtering(reader, parser, storage):
    parser.entry('1', 'b', title='bbb')
    parser.entry('1', 'c', title='ccc')
    reader.update_feeds()
    storage.changes.enable()
    storage.delete_entries([('1', 'a')])

    changes = storage.changes.get()

    # sanity check
    assert {(c.action, c.resource_id, c.tag_key) for c in changes} == {
        (Action.DELETE, ('1', 'a'), None),
        (Action.INSERT, ('1', 'b'), None),
        (Action.INSERT, ('1', 'c'), None),
    }

    assert storage.changes.get(limit=1) == changes[:1]
    assert storage.changes.get(limit=2) == changes[:2]

    deletes = storage.changes.get(Action.DELETE)
    assert {(c.action, c.resource_id, c.tag_key) for c in deletes} == {
        (Action.DELETE, ('1', 'a'), None),
    }

    inserts = storage.changes.get(Action.INSERT)
    assert {(c.action, c.resource_id, c.tag_key) for c in inserts} == {
        (Action.INSERT, ('1', 'b'), None),
        (Action.INSERT, ('1', 'c'), None),
    }

    (first_insert,) = storage.changes.get(Action.INSERT, limit=1)
    assert first_insert in inserts


def test_done_partial(reader, storage):
    reader._parser.entry('1', 'b', title='bbb')
    reader.update_feeds()
    storage.changes.enable()

    changes = storage.changes.get()
    a_change, b_change = sorted(changes, key=lambda c: c.resource_id)
    storage.changes.done([a_change])

    assert storage.changes.get() == [b_change]


def test_done_unknown(reader, storage):
    reader.patch_randomblob()
    reader.update_feeds()
    storage.changes.enable()

    # sanity check
    assert storage.changes.get() == [Change(Action.INSERT, b'seq1', ('1', 'a'))]

    # shouldn't raise
    storage.changes.done(
        [
            Change(Action.DELETE, b'seq1', ('1', 'a')),
            Change(Action.INSERT, b'seq2', ('1', 'a')),
            Change(Action.INSERT, b'abc', ('2',)),
            Change(Action.INSERT, b'abc', ('2', 'a')),
            Change(Action.INSERT, b'abc', (), 'key'),
            Change(Action.INSERT, b'abc', ('2',), 'key'),
            Change(Action.INSERT, b'abc', ('2', 'a'), 'key'),
        ]
    )

    # still there
    assert storage.changes.get() == [Change(Action.INSERT, b'seq1', ('1', 'a'))]


def test_chunk_size(reader, parser, storage):
    parser.entry('1', 'b', title='bbb')
    reader.update_feeds()
    storage.changes.enable()

    changes = storage.changes.get()

    storage.chunk_size = 1
    assert storage.changes.get() == changes[:1]

    with pytest.raises(ValueError):
        storage.changes.done(changes)


def test_randomblob(reader, storage):
    reader.update_feeds()
    storage.changes.enable()

    (change,) = storage.changes.get()

    assert isinstance(change.sequence, bytes)
    assert len(change.sequence) == 16
    assert get_entries(reader) == {('1', 'a', change.sequence)}
