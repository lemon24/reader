from reader._plugins import global_metadata


def test_plugin(make_reader, db_path):
    reader = make_reader(db_path, plugins=[global_metadata.init_reader])
    reader = make_reader(db_path, plugins=[global_metadata.init_reader])

    reader.update_feeds()

    assert dict(reader.get_global_metadata()) == {'.reader.hidden': None}
    assert reader.get_global_metadata_item('one', None) is None

    reader.set_global_metadata_item('one', [1])
    assert dict(reader.get_global_metadata()) == {'.reader.hidden': None, 'one': [1]}
    assert reader.get_global_metadata_item('one') == [1]

    reader.set_global_metadata_item('two', {'ii': 2})
    assert dict(reader.get_global_metadata()) == {
        '.reader.hidden': None,
        'one': [1],
        'two': {'ii': 2},
    }
    assert reader.get_global_metadata_item('two') == {'ii': 2}

    reader.delete_global_metadata_item('one')
    assert reader.get_global_metadata_item('one', None) is None
    assert dict(reader.get_global_metadata()) == {
        '.reader.hidden': None,
        'two': {'ii': 2},
    }

    assert {f.url for f in reader.get_feeds()} == set()
    assert {f.url for f in type(reader).get_feeds(reader)} == {'reader:global-metadata'}
    reader.add_feed('http://example.com')
    assert {f.url for f in reader.get_feeds()} == {'http://example.com'}
