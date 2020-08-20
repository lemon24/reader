"""
Config file support.

https://github.com/lemon24/reader/issues/177

"""
import copy
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field

from reader import make_reader
from reader._plugins import import_string
from reader._plugins import Loader


MAKE_READER_IMPORT_KWARGS = ('storage_cls', 'search_cls')


def make_reader_from_config(*, plugins=None, plugin_loader_cls=Loader, **kwargs):
    """Like reader.make_reader(), but:

    * If *_cls arguments are str, import them.
    * Load plugins.

    """
    plugins = plugins or {}

    for name in MAKE_READER_IMPORT_KWARGS:
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


def make_reader_config(thing):
    if not isinstance(thing, Mapping):
        raise ValueError("config must be a mapping")
    # TODO: validate / raise nicer exceptions here
    return Config(
        copy.deepcopy(thing), sections={'cli', 'app'}, merge_keys={'reader', 'plugins'}
    )


def _merge_config(*configs, merge_keys=()):
    """Merge multiple make_app_from_config() kwargs dicts into a single one.

    plugins is assumed to be a dict and is merged. All other keys are replaced.

    """
    rv = {}
    to_merge = {}

    for config in configs:
        config = config.copy()
        for name in merge_keys:
            if name in config:
                to_merge.setdefault(name, []).append(config.pop(name))
        rv.update(config)

    for name, dicts in to_merge.items():
        rv[name] = _merge_config(*dicts, merge_keys=merge_keys)

    return rv


@dataclass
class Config:

    data: dict = field(default_factory=dict)
    sections: set = field(default_factory=set)
    merge_keys: set = field(default_factory=set)
    default_section: str = 'default'

    def __post_init__(self):
        self.sections.add(self.default_section)

        unknown_sections = self.data.keys() - self.sections

        if self.default_section in self.data:
            if unknown_sections:
                raise ValueError(f"unknown sections in config: {unknown_sections!r}")
        else:
            self.data[self.default_section] = {
                section: self.data.pop(section) for section in unknown_sections
            }

            # default is always first
            for section in list(self.data):
                if section != self.default_section:
                    self.data[section] = self.data.pop(section)

        for section in self.sections:
            self.data.setdefault(section, {})

    def merged(self, section, overrides=None):
        if section not in self.sections:
            raise ValueError(f"unknown section: {section!r}")

        return _merge_config(
            self.data[self.default_section],
            self.data[section],
            overrides or {},
            merge_keys=self.merge_keys,
        )

    def merge_all(self):
        config = copy.deepcopy(self)
        for section in list(config.data):
            if section != config.default_section:
                config.data[section] = config.merged(section)
        return config

    def make_reader(self, section, **kwargs):
        return make_reader_from_config(
            **self.merged(section, {'reader': kwargs}).get('reader', {}),
        )

    @property
    def all(self):
        return MultiMapping(list(self.data.values()))

    def __getitem__(self, key):
        return self.data[key]


@dataclass
class MultiMapping:

    mappings: list = field(default_factory=list)
    default_factory: callable = dict

    def __getitem__(self, key):
        return MultiMapping(
            [
                mapping.setdefault(key, self.default_factory())
                for mapping in self.mappings
            ],
            self.default_factory,
        )

    def __setitem__(self, key, value):
        for mapping in self.mappings:
            mapping[key] = value
