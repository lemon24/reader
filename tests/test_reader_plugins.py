import pytest

from reader import InvalidPluginError
from reader import PluginInitError


@pytest.fixture(autouse=True)
def set_module_prefix(monkeypatch):
    monkeypatch.setattr('reader.plugins._MODULE_PREFIX', 'reader_test_plugins.')


def test_good(monkeypatch, make_reader):
    def one(reader):
        one.reader = reader

    def two(reader):
        two.reader = reader

    monkeypatch.setattr('reader_test_plugins.good.init_reader', one)

    reader = make_reader(':memory:', plugins=['reader.good', two])

    assert one.reader is reader
    assert two.reader is reader


@pytest.mark.parametrize(
    'plugin_name',
    ['reader_test_plugins.good:init_reader', 'reader_test_plugins.good.init_reader'],
)
def test_good_full_path(monkeypatch, make_reader, plugin_name):
    monkeypatch.setattr('reader.plugins._PLUGIN_PREFIX', 'reader_test_plugins.')

    def one(reader):
        one.reader = reader

    monkeypatch.setattr('reader_test_plugins.good.init_reader', one)

    reader = make_reader(':memory:', plugins=[plugin_name])

    assert one.reader is reader


def test_init_error_built_in(make_reader):
    with pytest.raises(PluginInitError) as exc_info:
        reader = make_reader(':memory:', plugins=['reader.init_error'])

    message = str(exc_info.value)
    assert 'reader_test_plugins.init_error:init_reader' in message
    assert 'someerror' in message


def test_init_error_callable(make_reader):
    from reader_test_plugins.init_error import init_reader as plugin

    with pytest.raises(PluginInitError) as exc_info:
        reader = make_reader(':memory:', plugins=[plugin])

    message = str(exc_info.value)
    assert 'reader_test_plugins.init_error:init_reader' in message
    assert 'someerror' in message


def test_non_built_in(monkeypatch, make_reader):
    with pytest.raises(InvalidPluginError) as exc_info:
        make_reader(':memory:', plugins=['reader_test_plugins.good:init_reader'])

    assert "no such built-in plugin: 'reader_test_plugins.good:init_reader'" in str(
        exc_info.value
    )


def test_missing_plugin(make_reader):
    with pytest.raises(InvalidPluginError) as exc_info:
        make_reader(':memory:', plugins=['reader.unknown'])

    assert "no such built-in plugin: 'reader.unknown'" in str(exc_info.value)


def test_missing_entry_point(make_reader):
    with pytest.raises(AttributeError) as exc_info:
        make_reader(':memory:', plugins=['reader.missing_entry_point'])


def test_missing_dependency(make_reader):
    with pytest.raises(ImportError) as exc_info:
        make_reader(':memory:', plugins=['reader.missing_dependency'])
