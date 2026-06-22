import gzip
import pathlib
import shutil
from datetime import datetime
from datetime import timezone


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
