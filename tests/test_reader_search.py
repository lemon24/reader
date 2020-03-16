import pytest


def test_nothing_is_actually_working_searchwise(reader):
    with pytest.raises(Exception):
        reader.update_search()
    with pytest.raises(Exception):
        list(reader.search_entries('one'))
    with pytest.raises(Exception):
        reader.disable_search()


def test_search_disabled_by_default(reader):
    assert not reader.is_search_enabled()


def test_enable_search(reader):
    assert not reader.is_search_enabled()
    reader.enable_search()
    assert reader.is_search_enabled()


# TODO: actual tests
