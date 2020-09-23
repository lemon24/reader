import sqlite3
import sys

import pytest

from reader._sqlite_utils import ddl_transaction
from reader._sqlite_utils import HeavyMigration
from reader._sqlite_utils import IntegrityError
from reader._sqlite_utils import require_compile_options
from reader._sqlite_utils import require_version
from reader._sqlite_utils import RequirementError
from reader._sqlite_utils import SchemaVersionError
from reader._sqlite_utils import setup_db
from reader._sqlite_utils import wrap_exceptions


def dummy_ddl_transaction(db):
    """Just use a regular transaction."""
    return db


@pytest.mark.parametrize(
    'ddl_transaction',
    [
        # Fails on PyPy3 7.2.0, but not on CPython or PyPy3 7.3.1 (on macOS, at least).
        pytest.param(
            dummy_ddl_transaction,
            marks=pytest.mark.xfail(
                "sys.implementation.name == 'pypy' "
                # For some reason, this doesn't work:
                # https://travis-ci.org/github/lemon24/reader/jobs/684668462
                # "and sys.pypy_version_info <= (7, 2, 0)",
                # strict=True,
            ),
        ),
        ddl_transaction,
    ],
)
def test_ddl_transaction_create_and_insert(ddl_transaction):
    db = sqlite3.connect(':memory:')

    with db:
        db.execute("create table t (a, b);")
        db.execute("insert into t values (1, 2);")

    assert list(db.execute("select * from t order by a;")) == [(1, 2)]

    with pytest.raises(ZeroDivisionError):
        with ddl_transaction(db):
            db.execute("insert into t values (3, 4);")
            db.execute("alter table t add column c;")
            1 / 0

    assert list(db.execute("select * from t order by a;")) == [(1, 2)]


@pytest.mark.parametrize(
    'ddl_transaction',
    [
        # still fails, even on Python 3.6+
        pytest.param(dummy_ddl_transaction, marks=pytest.mark.xfail(strict=True)),
        ddl_transaction,
    ],
)
def test_ddl_transaction_create_only(ddl_transaction):
    db = sqlite3.connect(':memory:')

    assert len(list(db.execute("PRAGMA table_info(t);"))) == 0

    with pytest.raises(ZeroDivisionError):
        with ddl_transaction(db):
            db.execute("create table t (a, b);")
            1 / 0

    assert len(list(db.execute("PRAGMA table_info(t);"))) == 0


class SomeError(Exception):
    pass


def test_wrap_exceptions():
    db = sqlite3.connect('file::memory:?mode=ro', uri=True)

    with pytest.raises(SomeError) as excinfo:
        with wrap_exceptions(SomeError):
            db.execute('create table t (a)')
    assert isinstance(excinfo.value.__cause__, sqlite3.OperationalError)
    assert 'unexpected error' in str(excinfo.value)

    # non- "cannot operate on a closed database" ProgrammingError
    with pytest.raises(sqlite3.Error) as excinfo:
        with wrap_exceptions(SomeError):
            db.execute('values (:a)', {})

    # works now
    db.execute('values (1)')

    # doesn't after closing
    db.close()
    with pytest.raises(SomeError) as excinfo:
        with wrap_exceptions(SomeError):
            db.execute('values (1)')
    assert excinfo.value.__cause__ is None
    assert 'closed database' in str(excinfo.value)


class WeirdError(Exception):
    pass


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
    assert excinfo.value.args == ('create',)
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
    assert excinfo.value.args == ('update',)
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


def test_migration_invalid_version_table():
    db = sqlite3.connect(':memory:')
    with db:
        db.execute("CREATE TABLE version (not_version);")
    migration = HeavyMigration(create_db_2, 2, {})
    with pytest.raises(SchemaVersionError) as excinfo:
        migration.migrate(db)


def test_migration_integrity_error():
    def create_db(db):
        db.execute("CREATE TABLE t (one INTEGER PRIMARY KEY);")
        db.execute(
            "CREATE TABLE u (two INTEGER NOT NULL, FOREIGN KEY (two) REFERENCES t(one));"
        )

    def update_from_1_to_2(db):
        db.execute("INSERT INTO u VALUES (1);")

    db = sqlite3.connect(':memory:')
    db.execute("PRAGMA foreign_keys = ON;")

    migration = HeavyMigration(create_db, 1, {})
    migration.migrate(db)
    migration = HeavyMigration(create_db, 2, {1: update_from_1_to_2})
    with pytest.raises(IntegrityError):
        migration.migrate(db)


def test_require_version():
    db = MockConnection(execute_rv=[('3.15.0',)])

    with pytest.raises(RequirementError):
        require_version(db, (3, 16, 0))

    # shouldn't raise an exception
    require_version(db, (3, 15, 0))
    require_version(db, (3, 14))


class MockConnection:
    def __init__(self, *, execute_rv=None):
        self._execute_rv = execute_rv

    def execute(self, *args):
        return self._execute_rv

    def cursor(self):
        return self

    def close(self):
        pass


def test_require_compile_options():
    db = MockConnection(execute_rv=[('ONE',), ('TWO',)])

    with pytest.raises(RequirementError):
        require_compile_options(db, ['THREE'])
    with pytest.raises(RequirementError):
        require_compile_options(db, ['ONE', 'THREE'])

    # shouldn't raise an exception
    require_compile_options(db, ['ONE'])
    require_compile_options(db, ['ONE', 'TWO'])


@pytest.mark.parametrize(
    'wal_enabled, expected_mode', [(None, 'memory'), (True, 'wal'), (False, 'delete')]
)
def test_setup_db_wal_enabled(db_path, wal_enabled, expected_mode):
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode = MEMORY;").close()

    setup_db(
        db,
        create=lambda db: None,
        version=0,
        migrations={},
        minimum_sqlite_version=(3, 15, 0),
        wal_enabled=wal_enabled,
    )

    ((mode,),) = db.execute("PRAGMA journal_mode;")
    assert mode.lower() == expected_mode
