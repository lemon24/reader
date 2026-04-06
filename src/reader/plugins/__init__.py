"""
Built-in plug-ins.

While the plugin entry points are stable,
the plugin implementation is *not*.

"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from ._loader import PluginLoader

if TYPE_CHECKING:  # pragma: no cover
    from .. import Reader  # noqa: F401


#: The :func:`~reader.make_reader` default list of :ref:`plugins <plugins>`.
DEFAULT_PLUGINS = [
    '.ua_fallback',
]


_LEGACY_PLUGINS = {
    'reader.enclosure_dedupe',
    'reader.entry_dedupe',
    'reader.mark_as_read',
    'reader.readtime',
    'reader.ua_fallback',
}


def _process_legacy(name: str) -> str | None:
    # TODO: Remove legacy reader.<plugin> support in 4.0.
    if name not in _LEGACY_PLUGINS:
        return None
    new_name = name.removeprefix('reader')
    warnings.warn(
        "Support for built-in plugin names starting with 'reader.' "
        "is deprecated and will be removed in reader 4.0. "
        f"Use {new_name!r} instead of {name!r}.",
        DeprecationWarning,
        stacklevel=5,
    )
    return new_name


_PLUGIN_LOADER = PluginLoader['Reader'](
    'init_reader', 'reader.plugins', _process_legacy
)
