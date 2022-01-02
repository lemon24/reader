"""
Built-in plug-ins.

"""
from . import enclosure_dedupe
from . import entry_dedupe
from . import mark_as_read
from . import ua_fallback


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
