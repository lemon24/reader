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

        with pytest.raises(not_found_exc) as excinfo:
            reader.set_tag(resource, 'one')

    with subtests.test("delete tag"):
        with raises_TagNotFoundError(resource, 'one'):
            reader.delete_tag(resource, 'one')

        reader.delete_tag(resource, 'tag', missing_ok=True)


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

    reader.set_tag(resource, 'one', 'old')

    with subtests.test("get tag"):
        assert sorted(reader.get_tags(resource)) == [('one', 'old')]
        assert reader.get_tag(resource, 'one') == 'old'
        assert reader.get_tag(resource, 'one', 'default') == 'old'

    reader.set_tag(resource, 'one', 'new')

    with subtests.test("get tag after update"):
        assert sorted(reader.get_tags(resource)) == [('one', 'new')]
        assert reader.get_tag(resource, 'one') == 'new'
        assert reader.get_tag(resource, 'one', 'default') == 'new'

    reader.set_tag(resource, 'two', {2: ['ii']})

    with subtests.test("get tag, multiple"):
        assert sorted(reader.get_tags(resource)) == [
            ('one', 'new'),
            ('two', {'2': ['ii']}),
        ]
        assert sorted(reader.get_tags(resource, key='one')) == [('one', 'new')]
        assert reader.get_tag(resource, 'one') == 'new'
        assert reader.get_tag(resource, 'two') == {'2': ['ii']}

    reader.delete_tag(resource, 'two')

    with subtests.test("get tag after delete"):
        assert sorted(reader.get_tags(resource)) == [('one', 'new')]
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
    'one, two, wildcard',
    {
        'feed': ('1', '2', (None,)),
        'entry': (('1', '1, 1'), ('2', '2, 1'), (None, None)),
    },
)
@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 1])
def test_as_tags(reader, subtests, chunk_size, one, two, wildcard):
    reader._storage.chunk_size = chunk_size
    reader._parser = parser = Parser()
    parser.feed(1)
    parser.entry(1, 1)
    parser.feed(2)
    parser.entry(2, 1)
    reader.add_feed('1')
    reader.add_feed('2')
    reader.update_feeds()

    with subtests.test("no tags"):
        assert list(reader.get_tag_keys(one)) == []
        assert list(reader.get_tag_keys()) == []
        assert list(reader.get_tag_keys(None)) == []
        assert list(reader.get_tag_keys(wildcard)) == []

    reader.set_tag(one, 'tag-1')

    with subtests.test("one tag"):
        assert list(reader.get_tag_keys(one)) == ['tag-1']
        assert list(reader.get_tag_keys()) == ['tag-1']

    with subtests.test("adding tag twice does not raise"):
        reader.set_tag(one, 'tag-1')

    reader.set_tag(two, 'tag-2-2')
    reader.set_tag(two, 'tag-2-1')

    with subtests.test("many tags"):
        assert list(reader.get_tag_keys(one)) == ['tag-1']
        assert list(reader.get_tag_keys(two)) == ['tag-2-1', 'tag-2-2']
        assert list(reader.get_tag_keys()) == ['tag-1', 'tag-2-1', 'tag-2-2']
        assert list(reader.get_tag_keys(None)) == ['tag-1', 'tag-2-1', 'tag-2-2']
        assert list(reader.get_tag_keys(wildcard)) == ['tag-1', 'tag-2-1', 'tag-2-2']

    reader.delete_tag(one, 'tag-2-1', missing_ok=True)

    with subtests.test("after delete"):
        assert list(reader.get_tag_keys(one)) == ['tag-1']
        assert list(reader.get_tag_keys(two)) == ['tag-2-1', 'tag-2-2']
        assert list(reader.get_tag_keys()) == ['tag-1', 'tag-2-1', 'tag-2-2']

    reader.delete_tag(two, 'tag-2-1', missing_ok=True)

    with subtests.test("after another delete"):
        assert list(reader.get_tag_keys(one)) == ['tag-1']
        assert list(reader.get_tag_keys(two)) == ['tag-2-2']
        assert list(reader.get_tag_keys()) == ['tag-1', 'tag-2-2']

    reader.set_tag(two, 'tag-2-3')
    reader.set_tag(two, 'tag-2-0')
    reader.set_tag(two, 'tag-2-1')
    reader.set_tag(one, 'tag-common')
    reader.set_tag(two, 'tag-common')

    with subtests.test("ordering and uninon"):
        assert list(reader.get_tag_keys(one)) == ['tag-1', 'tag-common']
        assert list(reader.get_tag_keys(two)) == [
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
        assert list(reader.get_tag_keys(wildcard)) == [
            'tag-1',
            'tag-2-0',
            'tag-2-1',
            'tag-2-2',
            'tag-2-3',
            'tag-common',
        ]

    reader.delete_feed('2')

    with subtests.test("after delete resource"):
        assert list(reader.get_tag_keys(one)) == ['tag-1', 'tag-common']
        assert list(reader.get_tag_keys(two)) == []
        assert list(reader.get_tag_keys()) == ['tag-1', 'tag-common']


@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 1])
def test_as_tags_global(reader, subtests, chunk_size):
    """Subset of test_as_tags() that works for global tags."""

    reader._storage.chunk_size = chunk_size

    with subtests.test("no tags"):
        assert list(reader.get_tag_keys(())) == []
        assert list(reader.get_tag_keys()) == []
        assert list(reader.get_tag_keys(None)) == []

    reader.set_tag((), 'tag-1')

    with subtests.test("one tag"):
        assert list(reader.get_tag_keys(())) == ['tag-1']
        assert list(reader.get_tag_keys()) == ['tag-1']

    with subtests.test("adding tag twice does not raise"):
        reader.set_tag((), 'tag-1')

    reader.set_tag((), 'tag-2')

    with subtests.test("many tags"):
        assert list(reader.get_tag_keys(())) == ['tag-1', 'tag-2']
        assert list(reader.get_tag_keys()) == ['tag-1', 'tag-2']
        assert list(reader.get_tag_keys(None)) == ['tag-1', 'tag-2']

    reader.delete_tag((), 'tag-2', missing_ok=True)

    with subtests.test("after delete"):
        assert list(reader.get_tag_keys(())) == ['tag-1']
        assert list(reader.get_tag_keys()) == ['tag-1']

    reader.set_tag((), 'tag-3')
    reader.set_tag((), 'tag-0')

    with subtests.test("ordering"):
        assert list(reader.get_tag_keys(())) == ['tag-0', 'tag-1', 'tag-3']
        assert list(reader.get_tag_keys()) == ['tag-0', 'tag-1', 'tag-3']


@pytest.mark.parametrize('chunk_size', [Storage.chunk_size, 1])
def test_wildcard_interaction(reader, chunk_size):
    reader._storage.chunk_size = chunk_size
    reader._parser = parser = Parser()
    parser.feed(1)
    parser.entry(1, 1)
    parser.feed(2)
    parser.entry(2, 1)
    reader.add_feed('1')
    reader.add_feed('2')
    reader.update_feeds()

    reader.set_tag(('2', '2, 1'), '6-entry')
    reader.set_tag('1', '4-feed')
    reader.set_tag(('1', '1, 1'), '2-entry')
    reader.set_tag((), '5-global')
    reader.set_tag((), '3-global')
    reader.set_tag('2', '1-feed')

    assert list(reader.get_tag_keys((None,))) == ['1-feed', '4-feed']
    assert list(reader.get_tag_keys((None, None))) == ['2-entry', '6-entry']
    assert list(reader.get_tag_keys(())) == ['3-global', '5-global']
    assert list(reader.get_tag_keys()) == [
        '1-feed',
        '2-entry',
        '3-global',
        '4-feed',
        '5-global',
        '6-entry',
    ]
    assert list(reader.get_tag_keys(None)) == [
        '1-feed',
        '2-entry',
        '3-global',
        '4-feed',
        '5-global',
        '6-entry',
    ]


@parametrize_dict(
    'resource',
    {
        'feed': '1',
        'entry': ('1', '1, 1'),
        'global': (),
    },
)
@pytest.mark.parametrize('value', [0, 1, 'value', {}, False, None, {'complex': [1]}])
def test_set_no_value(reader, resource, value):
    reader._parser = parser = Parser()
    feed = parser.feed(1)
    entry = parser.entry(1, 1)
    reader.add_feed(feed)
    reader.update_feeds()

    reader.set_tag(resource, 'one', value)
    reader.set_tag(resource, 'two')
    reader.set_tag(resource, 'one')
    assert dict(reader.get_tags(resource)) == {'one': value, 'two': None}
    assert set(reader.get_tag_keys(resource)) == {'one', 'two'}


@parametrize_dict(
    'make_resource_arg',
    {
        'global': lambda *_: (),
        'feed': lambda f, _: f,
        'feed_id': lambda f, _: f.object_id,
        'feed_tuple': lambda f, _: (f.url,),
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
    assert list(reader.get_tags(resource)) == [('one', 'value')]
    assert list(reader.get_tag_keys(resource)) == ['one']
    assert reader.get_tag(resource, 'one') == 'value'
    reader.delete_tag(resource, 'one')


@pytest.mark.parametrize(
    'resource',
    # a small subset of the _resource_argument() bad arguments
    [1, ('a', 2), Entry('entry', feed=Feed(None))],
)
def test_resource_argument_valueerror(reader, resource):
    with pytest.raises(ValueError):
        reader.set_tag(resource, 'one', 'value')
    with pytest.raises(ValueError):
        list(reader.get_tags(resource))
    with pytest.raises(ValueError):
        list(reader.get_tag_keys(resource))
    with pytest.raises(ValueError):
        reader.get_tag(resource, 'one')
    with pytest.raises(ValueError):
        reader.delete_tag(resource, 'one')


@pytest.mark.parametrize(
    'resource',
    [
        None,
        (None,),
        (None, None),
        ('feed', None),
        (None, 'entry'),
    ],
)
def test_get_tags_wildcard_valueerror(reader, resource):
    with pytest.raises(ValueError):
        list(reader.get_tags(resource))


@pytest.mark.parametrize('resource', [('feed', None), (None, 'entry')])
def test_get_tag_keys_wildcard_valueerror(reader, resource):
    with pytest.raises(ValueError):
        list(reader.get_tag_keys(resource))
