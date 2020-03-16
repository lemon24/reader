import pytest


def test_nothing_is_actually_working_searchwise(reader):
    with pytest.raises(Exception):
        reader.enable_search()
    with pytest.raises(Exception):
        reader.is_search_enabled()
    with pytest.raises(Exception):
        reader.update_search()
    with pytest.raises(Exception):
        list(reader.search_entries('one'))
    with pytest.raises(Exception):
        reader.disable_search()


# TODO: actual tests
