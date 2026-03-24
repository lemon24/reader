from types import SimpleNamespace

import pytest

from reader import InvalidPluginError
from reader import PluginInitError
from reader.plugins._loader import PluginLoader


def init_reader(reader):
    reader.default = True


def absolute(reader):
    reader.absolute = True


def test_load_init_many():

    def callable(reader):
        reader.callable = True

    loader = PluginLoader('init_reader', '_plugins')
    plugins = loader.load_many(
        [callable, '.builtin', 'test_plugins_loader', 'test_plugins_loader:absolute']
    )

    target = SimpleNamespace()
    loader.init_many(target, plugins)

    assert set(target.__dict__) == {'callable', 'builtin', 'default', 'absolute'}


@pytest.mark.parametrize(
    'name',
    [
        '',
        '.',
        'a:b:c',
        '.inexistent',
        '.error_import_error',
        'inexistent',
        'typing',
        'typing:inexistent',
    ],
)
def test_not_found_error(name):
    loader = PluginLoader('init_reader', '_plugins')

    with pytest.raises(InvalidPluginError) as exc_info:
        loader.load(name)

    assert 'no such' in str(exc_info.value)
    assert name in str(exc_info.value)
    assert isinstance(
        exc_info.value.__cause__, (ValueError, ImportError, AttributeError)
    )


def test_error_during_import():
    loader = PluginLoader('init_reader', '_plugins')
    name = '.error_during_import'

    with pytest.raises(InvalidPluginError) as exc_info:
        loader.load(name)

    assert 'during plugin import' in str(exc_info.value)
    assert name in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_no_builtins_error():
    loader = PluginLoader('init_reader')
    name = '.builtin'

    with pytest.raises(InvalidPluginError) as exc_info:
        loader.load('.builtin')

    assert 'not supported' in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_init_many_error():
    cause = RuntimeError('error')

    def raise_exc(_):
        raise cause

    loader = PluginLoader('init_reader')

    with pytest.raises(PluginInitError) as exc_info:
        loader.oneshot(None, [raise_exc])

    assert 'during plugin initialization' in str(exc_info.value)
    assert 'test_plugins_loader' in str(exc_info.value)
    assert 'raise_exc' in str(exc_info.value)
    assert exc_info.value.__cause__ is cause
