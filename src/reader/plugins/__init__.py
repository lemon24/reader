"""
Built-in plug-ins.

"""
from typing import Callable
from typing import Iterable
from typing import TYPE_CHECKING
from typing import Union

from . import enclosure_dedupe
from . import entry_dedupe
from . import mark_as_read
from . import ua_fallback
from ..exceptions import InvalidPluginError

if TYPE_CHECKING:  # pragma: no cover
    from . import Reader


_PLUGINS = {
    'reader.enclosure_dedupe': enclosure_dedupe.init_reader,
    'reader.entry_dedupe': entry_dedupe.init_reader,
    'reader.mark_as_read': mark_as_read.init_reader,
    'reader.ua_fallback': ua_fallback.init_reader,
}

#: The list of plugins :func:`~reader.make_reader` uses by default.
DEFAULT_PLUGINS = [
    'reader.ua_fallback',
]


PluginType = Callable[['Reader'], None]
PluginInput = Union[str, PluginType]


def _load_plugins(plugins: Iterable[PluginInput]) -> Iterable[PluginType]:
    for plugin in plugins:
        if isinstance(plugin, str):
            if plugin not in _PLUGINS:
                raise InvalidPluginError(f"no such built-in plugin: {plugin!r}")
            plugin_func = _PLUGINS[plugin]
        else:
            plugin_func = plugin
        yield plugin_func
