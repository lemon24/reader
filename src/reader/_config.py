"""
Config file support.

https://github.com/lemon24/reader/issues/177

"""

from reader import make_reader
from reader._plugins import Loader

from .plugins import DEFAULT_PLUGINS


MAKE_READER_IMPORT_KWARGS = ('storage_cls', 'search_cls')


def make_reader_from_config(*, plugins=None, plugin_loader=None, **kwargs):
    """Like reader.make_reader(), but:

    * If *_cls arguments are str, import them.
    * Load plugins.

    """
    loader = Loader()
    plugin_loader = plugin_loader or loader

    for name in MAKE_READER_IMPORT_KWARGS:
        # this is dead code until make_reader() actually gets those arguments
        thing = kwargs.get(name)
        if thing and isinstance(thing, str):
            # use the default loader for these (we always want exceptions)
            kwargs[name] = loader.load(name, wrap=True)

    plugins = plugins if plugins is not None else dict.fromkeys(DEFAULT_PLUGINS)

    plugins_arg = kwargs['plugins'] = []
    for name in list(plugins):
        if name.startswith('reader.'):
            plugins_arg.append(name)
        else:
            plugin = plugin_loader.load(name, wrap=True)
            if not plugin:
                continue
            plugins_arg.append(plugin)

    reader = make_reader(**kwargs)
    return reader
