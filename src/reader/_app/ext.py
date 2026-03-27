"""
Flask extension that encapsulates configurable reader-related aspects.

"""

from dataclasses import dataclass

from flask import current_app

from reader import make_reader
from reader.plugins._loader import PluginLoader


_plugin_loader = PluginLoader('init_app')


def get_reader():
    return current_app.extensions['reader'].get_reader()


class ReaderExtension:

    def __init__(self, app=None, state_cls=None):
        self.state_cls = state_cls or _ReaderState
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        config = app.config['READER']
        app.extensions['reader'] = self.state_cls(config[''])
        _plugin_loader.oneshot(app, config.get('web', {}).get('plugins', ()))


@dataclass
class ReaderStateBase:
    args: dict

    def get_reader(self):
        raise NotImplementedError

    def _make_reader(self, **kwargs):
        return make_reader(**self.args | kwargs)


class _ReaderState(ReaderStateBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reader = self._make_reader()

    def get_reader(self):
        return self._reader
