import pytest
from fakeparser import Parser

from reader import StorageError
from reader._types import Action
from reader._types import Change


def test_basic(reader):
    parser = reader._parser = Parser()
    storage = reader._storage

    randomblob_index = 0

    def randomblob(n):
        assert n == 16, n
        nonlocal randomblob_index
        randomblob_index += 1
        return f'seq{randomblob_index}'.encode()

    storage.get_db().create_function('randomblob', 1, randomblob)
    # storage.get_db().create_function('print', -1, print)

    def get_entries():
        return {(e.feed_url, e.id, e._sequence) for e in reader.get_entries()}

    reader.add_feed(parser.feed('1', title='one'))
    parser.entry('1', 'a', title='aaa')
    reader.update_feeds()

    assert reader.get_entry(('1', 'a'))._sequence is None
    # FIXME: check message
    with pytest.raises(StorageError):
        storage.changes.get()
    with pytest.raises(StorageError):
        # FIXME: should be a no-op
        storage.changes.disable()

    storage.changes.enable()

    with pytest.raises(StorageError):
        # FIXME: should be a no-op
        storage.changes.enable()

    assert get_entries() == {('1', 'a', b'seq1')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.INSERT, b'seq1', '1', 'a'),
    ]

    parser.entry('1', 'a', title='AAA')
    reader.update_feeds()
    assert get_entries() == {('1', 'a', b'seq2')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.DELETE, b'seq1', '1', 'a'),
        Change(Action.INSERT, b'seq2', '1', 'a'),
    ]
    storage.changes.done(changes)
    assert storage.changes.get() == []

    # FIXME: similar tests for content/summary

    parser.feed('1', title='one', author='author')
    parser.entry('1', 'a', title='AAA', link='link')
    reader.update_feeds()
    assert get_entries() == {('1', 'a', b'seq2')}
    assert storage.changes.get() == []

    parser.entry('1', 'b', title='bbb')
    reader.update_feeds()
    assert get_entries() == {('1', 'a', b'seq2'), ('1', 'b', b'seq3')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.INSERT, b'seq3', '1', 'b'),
    ]
    # don't clear, want to see if it changes to DELETE below

    reader.change_feed_url('1', '2')
    assert get_entries() == {('2', 'a', b'seq4'), ('2', 'b', b'seq5')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.DELETE, b'seq2', '1', 'a'),
        Change(Action.DELETE, b'seq3', '1', 'b'),
        Change(Action.INSERT, b'seq4', '2', 'a'),
        Change(Action.INSERT, b'seq5', '2', 'b'),
    ]

    # partial done (and also test get() filtering)
    storage.changes.done(storage.changes.get(action=Action.INSERT, limit=1))
    assert storage.changes.get() == [
        Change(Action.DELETE, b'seq2', '1', 'a'),
        Change(Action.DELETE, b'seq3', '1', 'b'),
        Change(Action.INSERT, b'seq5', '2', 'b'),
    ]
    # remaining done, unknown ignored
    storage.changes.done(changes)
    assert storage.changes.get() == []

    parser.feed('2', title='two')
    reader.update_feeds()
    assert get_entries() == {('2', 'a', b'seq6'), ('2', 'b', b'seq7')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.DELETE, b'seq4', '2', 'a'),
        Change(Action.DELETE, b'seq5', '2', 'b'),
        Change(Action.INSERT, b'seq6', '2', 'a'),
        Change(Action.INSERT, b'seq7', '2', 'b'),
    ]
    storage.changes.done(changes)

    reader.set_feed_user_title('2', 'my feed')
    assert get_entries() == {('2', 'a', b'seq8'), ('2', 'b', b'seq9')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.DELETE, b'seq6', '2', 'a'),
        Change(Action.DELETE, b'seq7', '2', 'b'),
        Change(Action.INSERT, b'seq8', '2', 'a'),
        Change(Action.INSERT, b'seq9', '2', 'b'),
    ]
    storage.changes.done(changes)

    storage.delete_entries([('2', 'a')])
    assert get_entries() == {('2', 'b', b'seq9')}
    changes = storage.changes.get()
    assert changes == [
        Change(Action.DELETE, b'seq8', '2', 'a'),
    ]

    reader.delete_feed('2')
    assert get_entries() == set()
    changes = storage.changes.get()

    assert changes == [
        Change(Action.DELETE, b'seq8', '2', 'a'),
        Change(Action.DELETE, b'seq9', '2', 'b'),
    ]

    storage.changes.disable()
    # FIXME: assert: entry seq is none, not enabled raises
