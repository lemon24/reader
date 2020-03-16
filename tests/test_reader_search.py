import pytest


def test_nothing_is_actually_working_searchwise(reader):
    with pytest.raises(Exception):
        reader.update_search()
    with pytest.raises(Exception):
        list(reader.search_entries('one'))


def test_search_disabled_by_default(reader):
    assert not reader.is_search_enabled()


def test_enable_search(reader):
    reader.enable_search()
    assert reader.is_search_enabled()


@pytest.mark.xfail(strict=True, reason="TODO: shouldn't fail")
def test_enable_search_already_enabled(reader):
    reader.enable_search()
    reader.enable_search()


def test_disable_search(reader):
    reader.enable_search()
    assert reader.is_search_enabled()
    reader.disable_search()
    assert not reader.is_search_enabled()


@pytest.mark.xfail(strict=True, reason="TODO: shouldn't fail")
def test_disable_search_already_disabled(reader):
    reader.disable_search()


# TODO: actual tests
