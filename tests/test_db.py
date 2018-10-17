import sqlite3

import pytest

from reader.db import ddl_transaction
from reader.db import HeavyMigration, SchemaVersionError
from reader.db import RequirementError
from reader.db import require_sqlite_version, require_sqlite_compile_options


class WeirdError(Exception): pass


def create_db_1(db):
    db.execute("CREATE TABLE t (one INTEGER);")

def create_db_2(db):
    db.execute("CREATE TABLE t (one INTEGER, two INTEGER);")

def create_db_2_error(db):
    create_db_2(db)
    raise WeirdError('create')

def update_from_1_to_2(db):
    db.execute("ALTER TABLE t ADD COLUMN two INTEGER;")

def update_from_1_to_2_error(db):
    update_from_1_to_2(db)
    raise WeirdError('update')


def test_migration_create():
    db = sqlite3.connect(':memory:')
    migration = HeavyMigration(create_db_2, 2, {})
    # should call migration.create but not migration.migrations[1]
    migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']

def test_migration_create_error():
    db = sqlite3.connect(':memory:')
    migration = HeavyMigration(create_db_2_error, 2, {})
    # should call migration.create but not migration.migrations[1]
    with pytest.raises(WeirdError) as excinfo:
        migration.migrate(db)
    assert excinfo.value.args == ('create', )
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == []

def test_migration_update():
    db = sqlite3.connect(':memory:')
    migration = HeavyMigration(create_db_1, 1, {})
    migration.migrate(db)
    migration = HeavyMigration(create_db_2_error, 2, {1: update_from_1_to_2})
    # should call migration.migrations[1] but not migration.create
    migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']

def test_migration_no_update():
    db = sqlite3.connect(':memory:')
    migration = HeavyMigration(create_db_2, 2, {})
    migration.migrate(db)
    migration = HeavyMigration(create_db_2_error, 2, {})
    # should call neither migration.create nor migration.migrations[1]
    migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']

def test_migration_update_error():
    db = sqlite3.connect(':memory:')
    migration = HeavyMigration(create_db_1, 1, {})
    migration.migrate(db)
    migration = HeavyMigration(create_db_2_error, 2, {1: update_from_1_to_2_error})
    # should call migration.migrations[1] but not migration.create
    with pytest.raises(WeirdError) as excinfo:
        migration.migrate(db)
    assert excinfo.value.args == ('update', )
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one']

def test_migration_unsupported_old_version():
    db = sqlite3.connect(':memory:')
    migration = HeavyMigration(create_db_1, 1, {})
    migration.migrate(db)
    migration = HeavyMigration(create_db_2, 2, {})
    with pytest.raises(SchemaVersionError) as excinfo:
        migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one']

def test_migration_unsupported_intermediary_version():
    db = sqlite3.connect(':memory:')
    migration = HeavyMigration(create_db_1, 1, {})
    migration.migrate(db)
    migration = HeavyMigration(create_db_2, 3, {1: update_from_1_to_2})
    with pytest.raises(SchemaVersionError) as excinfo:
        migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one']

def test_migration_invalid_version():
    db = sqlite3.connect(':memory:')
    migration = HeavyMigration(create_db_2, 2, {})
    migration.migrate(db)
    migration = HeavyMigration(create_db_1, 1, {})
    with pytest.raises(SchemaVersionError) as excinfo:
        migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']


def test_require_sqlite_version(monkeypatch):
    monkeypatch.setattr('sqlite3.sqlite_version_info', (3, 15, 0))

    with pytest.raises(RequirementError):
        require_sqlite_version((3, 16, 0))

    # shouldn't raise an exception
    require_sqlite_version((3, 15, 0))
    require_sqlite_version((3, 14))


class MockCursor:

    def __init__(self):
        self._execute_args = None
        self._fetchall_rv = None

    def execute(self, *args):
        self._execute_args = args

    def fetchall(self):
        return self._fetchall_rv

    def close(self):
        pass

class MockConnection:

    def __init__(self):
        self._cursor = MockCursor()

    def cursor(self):
        return self._cursor


def test_require_sqlite_compile_options():
    db = MockConnection()
    db._cursor._fetchall_rv = [('ONE', ), ('TWO', )]

    with pytest.raises(RequirementError):
        require_sqlite_compile_options(db, ['THREE'])
    with pytest.raises(RequirementError):
        require_sqlite_compile_options(db, ['ONE', 'THREE'])

    # shouldn't raise an exception
    require_sqlite_compile_options(db, ['ONE'])
    require_sqlite_compile_options(db, ['ONE', 'TWO'])


