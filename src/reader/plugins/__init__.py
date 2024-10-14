"""
Built-in plug-ins.

"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from pkgutil import resolve_name
from typing import TYPE_CHECKING
from typing import Union

from ..exceptions import InvalidPluginError


if TYPE_CHECKING:  # pragma: no cover
    from . import Reader


#: The :func:`~reader.make_reader` default list of :ref:`plugins <plugins>`.
DEFAULT_PLUGINS = [
    'reader.ua_fallback',
]

_PLUGIN_PREFIX = 'reader.'
_MODULE_PREFIX = 'reader.plugins.'


PluginType = Callable[['Reader'], None]
PluginInput = Union[str, PluginType]


def _load_plugins(plugins: Iterable[PluginInput]) -> Iterable[PluginType]:
    for plugin in plugins:
        yield _load_plugin(plugin)


def _load_plugin(plugin: PluginInput) -> PluginType:
    if not isinstance(plugin, str):
        return plugin

    if not plugin.startswith(_PLUGIN_PREFIX):
        raise InvalidPluginError(f"no such built-in plugin: {plugin!r}")

    module_name = plugin.replace(_PLUGIN_PREFIX, _MODULE_PREFIX, 1)
    import_error = None

    try:
        return resolve_name(module_name + ':init_reader')
    except ModuleNotFoundError as e:
        import_error = e
    except ValueError:
        pass

    try:
        return resolve_name(plugin)
    except (ModuleNotFoundError, AttributeError):
        pass

    if import_error and import_error.name != module_name:
        raise import_error

    raise InvalidPluginError(f"no such built-in plugin: {plugin!r}") from import_error
