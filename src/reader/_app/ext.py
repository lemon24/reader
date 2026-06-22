"""
Flask extension that encapsulates configurable reader-related aspects.

"""

import gzip
import pathlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone

from flask import current_app

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
        return Exports(self.get_reader(), self.get_user_cache_dir() / 'exports')


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


class Exports:

    max_files = 2

    def __init__(self, reader, path):
        self.reader = reader
        self.path = pathlib.Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def create(self):
        if len(list(self.path.glob('*'))) >= self.max_files:
            raise TooManyExportsError()

        now = self.reader._now()
        db = self.path / now.strftime("reader.sqlite.%Y-%m-%d-%H-%M-%S")
        gz = db.with_name(f"{db.name}.gz")
        gz_part = db.with_name(f"{gz.name}.part")

        try:
            self.reader._storage.get_db().execute("vacuum into ?", (str(db),))

            with open(db, 'rb') as db_file:
                with gzip.open(gz_part, 'wb') as gz_file:
                    shutil.copyfileobj(db_file, gz_file)

            gz_part.replace(gz)

        finally:
            db.unlink(missing_ok=True)

    def list(self):
        rv = []
        for path in self.path.glob("reader.sqlite.*.gz"):
            date = datetime.strptime(path.name, "reader.sqlite.%Y-%m-%d-%H-%M-%S.gz")
            date = date.replace(tzinfo=timezone.utc)
            rv.append((path, date))
        return rv

    def delete(self, name):
        assert '/' not in name
        (self.path / name).unlink()
