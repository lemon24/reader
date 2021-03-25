"""
Built-in plug-ins.

"""
from . import ua_fallback


_PLUGINS = {
    "reader.ua_fallback": ua_fallback.init_reader,
}

_DEFAULT_PLUGINS = ('reader.ua_fallback',)
