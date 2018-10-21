import pytest

from reader.storage import Storage
from reader.exceptions import StorageError
import reader.db


def test_storage_errors_open(tmpdir):
    # try to open a directory
    with pytest.raises(StorageError):
        Storage(str(tmpdir))


@pytest.mark.parametrize('db_error_cls', reader.db.db_errors)
def test_db_errors(monkeypatch, db_path, db_error_cls):
    """reader.db.DBError subclasses should be wrapped in StorageError."""

    def open_db(*args):
        raise db_error_cls("whatever")

    monkeypatch.setattr(Storage, '_open_db', staticmethod(open_db))

    with pytest.raises(StorageError):
        Storage(db_path)

