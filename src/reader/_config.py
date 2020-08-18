"""
Config file support.

https://github.com/lemon24/reader/issues/177

"""
from collections.abc import Mapping

from reader import make_reader
from reader._plugins import import_string
from reader._plugins import Loader


IMPORT_KWARGS = ('storage_cls', 'search_cls')
MERGE_KWARGS = ('plugins',)


def make_reader_from_config(*, plugins=None, plugin_loader_cls=Loader, **kwargs):
    """Like reader.make_reader(), but:

    * If *_cls arguments are str, import them.
    * Load plugins.

    """
    plugins = plugins or {}

    for name in IMPORT_KWARGS:
        thing = kwargs.get(name)
        if thing and isinstance(thing, str):
            kwargs[name] = import_string(thing)

    reader = make_reader(**kwargs)

    try:
        plugin_loader_cls(plugins).load_plugins(reader)
    except Exception:
        reader.close()
        raise

    return reader


def merge_config(*configs, merge_kwargs=MERGE_KWARGS):
    """Merge multiple make_app_from_config() kwargs dicts into a single one.

    plugins is assumed to be a dict and is merged. All other keys are replaced.

    """
    rv = {}
    to_merge = {}

    for config in configs:
        config = config.copy()
        for name in MERGE_KWARGS:
            if name in config:
                to_merge.setdefault(name, []).append(config.pop(name))
        rv.update(config)

    for name, dicts in to_merge.items():
        rv[name] = merge_config(*dicts, merge_kwargs=())

    return rv


def load_config(thing):
    if isinstance(thing, Mapping):
        config = thing
    else:
        import yaml

        config = yaml.safe_load(thing)
        if not isinstance(config, Mapping):
            raise ValueError("config must be a mapping")

    # TODO: validate / raise nicer exceptions here
    return config
