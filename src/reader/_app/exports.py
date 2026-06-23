import pathlib
from datetime import datetime
from datetime import timezone


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
        name_fmt = self.reader._storage.export_name(self.prefix_fmt)
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
        self.reader._storage.export(self.path, prefix)

    def exists(self, name):
        if not self.parse_name(name):
            return False
        return (self.path / name).exists()

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
