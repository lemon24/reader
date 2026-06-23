"""
Flask extension that encapsulates configurable reader-related aspects.

"""

import pathlib
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone

from flask import abort
from flask import current_app
from flask import send_from_directory

from reader import make_reader
from reader.plugins._loader import PluginLoader


def get_reader():
    return current_app.extensions['reader'].get_reader()


def get_exports():
    return current_app.extensions['reader'].get_exports()


_plugin_loader = PluginLoader('init_app')


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
        cache_dir = self.get_user_cache_dir()
        if not cache_dir:
            return None
        return Exports(self.get_reader(), cache_dir / 'exports')


class _ReaderState(ReaderStateBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reader = self._make_reader()
        self._exports = super().get_exports()

    def get_reader(self):
        return self._reader

    def get_user_cache_dir(self):
        return self.cache_dir

    def get_exports(self):
        return self._exports


class TooManyExportsError(Exception):
    pass


class ExportNotFoundError(Exception):
    pass


class Exports:

    max_files = 2
    prefix_fmt = "reader.%Y-%m-%d-%H-%M-%S"

    def __init__(self, reader, path):
        self.reader = reader
        self.path = pathlib.Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def parse_name(self, name):
        name_fmt = self.reader._storage.backup_name(self.prefix_fmt)
        try:
            dt = datetime.strptime(name, name_fmt)
        except ValueError:
            return None
        else:
            return dt.replace(tzinfo=timezone.utc)

    def create(self):
        # not looking at file names accounts for exports in progress
        if len(list(self.path.iterdir())) >= self.max_files:
            raise TooManyExportsError
        prefix = self.reader._now().strftime(self.prefix_fmt)
        self.reader._storage.backup(self.path, prefix)

    def get_response(self, name):
        if not self.parse_name(name):
            abort(404)
        return send_from_directory(get_exports().path, name, as_attachment=True)

    def list(self):
        rv = []
        for path in self.path.iterdir():
            if dt := self.parse_name(path.name):
                rv.append((path, dt))
        return rv

    def delete(self, name):
        if not self.parse_name(name):
            raise ExportNotFoundError
        try:
            (self.path / name).unlink()
        except FileNotFoundError:
            raise ExportNotFoundError from None
