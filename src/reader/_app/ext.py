"""
Flask extension that encapsulates configurable reader-related aspects.

"""

import pathlib
from dataclasses import dataclass

from flask import current_app

from reader import make_reader
from reader.plugins._loader import PluginLoader

from .exports import Exports

_plugin_loader = PluginLoader('init_app')


def get_reader():
    return current_app.extensions['reader'].get_reader()


def get_exports():
    return current_app.extensions['reader'].get_exports()


class ReaderExtension:

    def __init__(self, app=None, state_cls=None):
        self.state_cls = state_cls or _ReaderState
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        config = app.config['READER']
        app.extensions['reader'] = self.state_cls(
            config[''], config.get('web', {}).get('cache_dir')
        )
        _plugin_loader.oneshot(app, config.get('web', {}).get('plugins', ()))


@dataclass
class ReaderStateBase:
    args: dict
    cache_dir: pathlib.Path | None

    def get_reader(self):
        raise NotImplementedError

    def get_user_cache_dir(self):
        raise NotImplementedError

    def _make_reader(self, **kwargs):
        return make_reader(**self.args | kwargs)

    def get_exports(self):
        return Exports(self.get_reader(), self.get_user_cache_dir() / 'exports')


class _ReaderState(ReaderStateBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reader = self._make_reader()

    def get_reader(self):
        return self._reader

    def get_user_cache_dir(self):
        return self.cache_dir
