from contextlib import contextmanager

import pytest
from fakeparser import Parser
from utils import parametrize_dict

from reader import Entry
from reader import EntryNotFoundError
from reader import Feed
from reader import FeedNotFoundError
from reader import TagNotFoundError
from reader._storage import Storage


@contextmanager
def raises_TagNotFoundError(object_id, key):
    with pytest.raises(TagNotFoundError) as excinfo:
        yield
    assert excinfo.value.object_id == object_id
    assert excinfo.value.key == key
    assert 'no such tag' in excinfo.value.message


@parametrize_dict(
    'resource, not_found_exc',
    {
        'feed': ('1', FeedNotFoundError),
        'entry': (('1', '1, 1'), EntryNotFoundError),
        # no global, the global namespace always exists
    },
)
def test_inexistent_resource(reader, subtests, resource, not_found_exc):
    with subtests.test("get tag"):
        assert sorted(reader.get_tags(resource)) == []
        with raises_TagNotFoundError(resource, 'one'):
            reader.get_tag(resource, 'one')
        assert reader.get_tag(resource, 'one', 'default') == 'default'

    with subtests.test("set tag"):
        with pytest.raises(not_found_exc) as excinfo:
            reader.set_tag(resource, 'one', 'value')
        assert excinfo.value.object_id == resource
        assert 'no such' in excinfo.value.message
        assert 'no such tag' not in excinfo.value.message

    with subtests.test("delete tag"):
        with raises_TagNotFoundError(resource, 'one'):
            reader.delete_tag(resource, 'one')


@parametrize_dict(
    'resource',
    {
        'feed': '1',
        'entry': ('1', '1, 1'),
        'global': (),
    },
)
def test_as_metadata(reader, subtests, resource):
    reader._parser = parser = Parser()
    parser.feed(1)
    parser.entry(1, 1)
    reader.add_feed('1')
    reader.update_feeds()

    with subtests.test("get inexistent tag"):
        assert sorted(reader.get_tags(resource)) == []
        with raises_TagNotFoundError(resource, 'one'):
            reader.get_tag(resource, 'one')
        assert reader.get_tag(resource, 'one', 'default') == 'default'

    with subtests.test("delete inexistent tag"):
        with raises_TagNotFoundError(resource, 'one'):
            reader.delete_tag(resource, 'one')

    reader.set_tag(resource, 'one', 'value')

    with subtests.test("get tag"):
        assert sorted(reader.get_tags(resource)) == [('one', 'value')]
        assert reader.get_tag(resource, 'one') == 'value'
        assert reader.get_tag(resource, 'one', 'default') == 'value'

    reader.set_tag(resource, 'two', {2: ['ii']})

    with subtests.test("get tag, multiple"):
        assert sorted(reader.get_tags(resource)) == [
            ('one', 'value'),
            ('two', {'2': ['ii']}),
        ]
        assert sorted(reader.get_tags(resource, key='one')) == [('one', 'value')]
        assert reader.get_tag(resource, 'one') == 'value'
        assert reader.get_tag(resource, 'two') == {'2': ['ii']}

    reader.delete_tag(resource, 'two')

    with subtests.test("get tag after delete tag"):
        assert sorted(reader.get_tags(resource)) == [('one', 'value')]
        with raises_TagNotFoundError(resource, 'two'):
            reader.get_tag(resource, 'two')

    reader.delete_feed('1')

    with subtests.test("get tag after delete resource"):
        if resource == ():
            pytest.skip("global namespace cannot be deleted")
        assert sorted(reader.get_tags(resource)) == []
        with raises_TagNotFoundError(resource, 'one'):
            reader.get_tag(resource, 'one')


@parametrize_dict(
    'make_resource_arg',
    {
        'global': lambda *_: (),
        'feed': lambda f, _: f,
        'feed_id': lambda f, _: f.object_id,
        'entry': lambda _, e: e,
        'entry_id': lambda _, e: e.object_id,
    },
)
def test_resource_argument(reader, make_resource_arg):
    reader._parser = parser = Parser()
    feed = parser.feed(1)
    entry = parser.entry(1, 1)
    reader.add_feed(feed)
    reader.update_feeds()

    resource = make_resource_arg(feed, entry)

    reader.set_tag(resource, 'one', 'value')
    assert sorted(reader.get_tags(resource)) == [('one', 'value')]
    assert sorted(reader.get_tag_keys(resource)) == ['one']
    assert reader.get_tag(resource, 'one') == 'value'
    reader.delete_tag(resource, 'one')


# FIXME: parametrize test_as_tags()


@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 1])
def test_as_tags(reader, chunk_size):
    reader._storage.chunk_size = chunk_size

    with pytest.raises(FeedNotFoundError) as excinfo:
        reader.set_tag('one', 'tag')
    assert excinfo.value.url == 'one'
    assert 'no such feed' in excinfo.value.message

    # no-op
    reader.delete_tag('one', 'tag', missing_ok=True)

    # also no-op
    assert list(reader.get_tag_keys('one')) == []
    assert list(reader.get_tag_keys()) == []
    assert list(reader.get_tag_keys(None)) == []
    assert list(reader.get_tag_keys((None,))) == []

    reader.add_feed('one')
    reader.add_feed('two')

    # no tags
    assert list(reader.get_tag_keys('one')) == []
    assert list(reader.get_tag_keys()) == []

    reader.set_tag('one', 'tag-1')
    assert list(reader.get_tag_keys('one')) == ['tag-1']
    assert list(reader.get_tag_keys()) == ['tag-1']

    # no-op
    reader.set_tag('one', 'tag-1')

    reader.set_tag('two', 'tag-2-2')
    reader.set_tag('two', 'tag-2-1')
    assert list(reader.get_tag_keys('one')) == ['tag-1']
    assert list(reader.get_tag_keys('two')) == ['tag-2-1', 'tag-2-2']
    assert list(reader.get_tag_keys()) == ['tag-1', 'tag-2-1', 'tag-2-2']
    assert list(reader.get_tag_keys(None)) == ['tag-1', 'tag-2-1', 'tag-2-2']
    assert list(reader.get_tag_keys((None,))) == ['tag-1', 'tag-2-1', 'tag-2-2']

    # no-op
    reader.delete_tag('one', 'tag-2-1', missing_ok=True)
    assert list(reader.get_tag_keys('one')) == ['tag-1']
    assert list(reader.get_tag_keys('two')) == ['tag-2-1', 'tag-2-2']
    assert list(reader.get_tag_keys()) == ['tag-1', 'tag-2-1', 'tag-2-2']

    reader.delete_tag('two', 'tag-2-1', missing_ok=True)
    assert list(reader.get_tag_keys('one')) == ['tag-1']
    assert list(reader.get_tag_keys('two')) == ['tag-2-2']
    assert list(reader.get_tag_keys()) == ['tag-1', 'tag-2-2']

    reader.set_tag('two', 'tag-2-3')
    reader.set_tag('two', 'tag-2-0')
    reader.set_tag('two', 'tag-2-1')
    reader.set_tag('one', 'tag-common')
    reader.set_tag('two', 'tag-common')

    assert list(reader.get_tag_keys('one')) == ['tag-1', 'tag-common']
    assert list(reader.get_tag_keys('two')) == [
        'tag-2-0',
        'tag-2-1',
        'tag-2-2',
        'tag-2-3',
        'tag-common',
    ]
    assert list(reader.get_tag_keys()) == [
        'tag-1',
        'tag-2-0',
        'tag-2-1',
        'tag-2-2',
        'tag-2-3',
        'tag-common',
    ]

    reader.delete_feed('two')
    assert list(reader.get_tag_keys('one')) == ['tag-1', 'tag-common']
    assert list(reader.get_tag_keys('two')) == []
    assert list(reader.get_tag_keys()) == ['tag-1', 'tag-common']

    # TODO: test wildcards
    assert list(reader.get_tag_keys(())) == []
    assert list(reader.get_tag_keys(('a', 'b'))) == []


def test_set_arg_noop(reader):
    feed = 'http://www.example.com'
    reader.add_feed(feed)
    reader.set_tag(feed, 'one', {})
    reader.set_tag(feed, 'two')
    reader.set_tag(feed, 'one')
    assert dict(reader.get_tags(feed)) == {'one': {}, 'two': None}
    assert set(reader.get_tag_keys(feed)) == {'one', 'two'}
