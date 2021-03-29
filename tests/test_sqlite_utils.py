import sqlite3
import sys
from functools import wraps

import pytest
from utils import rename_argument

from reader._sqlite_utils import DBError
from reader._sqlite_utils import ddl_transaction
from reader._sqlite_utils import HeavyMigration
from reader._sqlite_utils import IdError
from reader._sqlite_utils import IntegrityError
from reader._sqlite_utils import NewMigration
from reader._sqlite_utils import OldMigration
from reader._sqlite_utils import require_compile_options
from reader._sqlite_utils import require_version
from reader._sqlite_utils import RequirementError
from reader._sqlite_utils import SchemaVersionError
from reader._sqlite_utils import setup_db
from reader._sqlite_utils import wrap_exceptions


original_sqlite3_connect = sqlite3.connect


@pytest.fixture(autouse=True)
def patch_sqlite3_connect(monkeypatch, request):
    @wraps(original_sqlite3_connect)
    def connect(*args, **kwargs):
        db = original_sqlite3_connect(*args, **kwargs)
        request.addfinalizer(db.close)
        return db

    monkeypatch.setattr('sqlite3.connect', connect)


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


@pytest.fixture(params=[HeavyMigration, NewMigration])
def migration_cls_no_id(request):
    # TODO: delete in 2.0; needed for the migration from OldMigration to NewMigration
    return request.param


@pytest.fixture(params=[0, 1234])
def migration_cls(request, migration_cls_no_id):
    return lambda *a, **kw: migration_cls_no_id(*a, id=request.param, **kw)


def test_migration_create(migration_cls):
    db = sqlite3.connect(':memory:')
    migration = migration_cls(create_db_2, 2, {})
    # should call migration.create but not migration.migrations[1]
    migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']


def test_migration_create_error(migration_cls):
    db = sqlite3.connect(':memory:')
    migration = migration_cls(create_db_2_error, 2, {})
    # should call migration.create but not migration.migrations[1]
    with pytest.raises(WeirdError) as excinfo:
        migration.migrate(db)
    assert excinfo.value.args == ('create',)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == []


def test_migration_update(migration_cls):
    db = sqlite3.connect(':memory:')
    migration = migration_cls(create_db_1, 1, {})
    migration.migrate(db)
    migration = migration_cls(create_db_2_error, 2, {1: update_from_1_to_2})
    # should call migration.migrations[1] but not migration.create
    migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']


def test_migration_no_update(migration_cls):
    db = sqlite3.connect(':memory:')
    migration = migration_cls(create_db_2, 2, {})
    migration.migrate(db)
    migration = migration_cls(create_db_2_error, 2, {})
    # should call neither migration.create nor migration.migrations[1]
    migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']


def test_migration_update_error(migration_cls):
    db = sqlite3.connect(':memory:')
    migration = migration_cls(create_db_1, 1, {})
    migration.migrate(db)
    migration = migration_cls(create_db_2_error, 2, {1: update_from_1_to_2_error})
    # should call migration.migrations[1] but not migration.create
    with pytest.raises(WeirdError) as excinfo:
        migration.migrate(db)
    assert excinfo.value.args == ('update',)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one']


def test_migration_unsupported_old_version(migration_cls):
    db = sqlite3.connect(':memory:')
    migration = migration_cls(create_db_1, 1, {})
    migration.migrate(db)
    migration = migration_cls(create_db_2, 2, {})
    with pytest.raises(SchemaVersionError) as excinfo:
        migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one']


def test_migration_unsupported_intermediary_version(migration_cls):
    db = sqlite3.connect(':memory:')
    migration = migration_cls(create_db_1, 1, {})
    migration.migrate(db)
    migration = migration_cls(create_db_2, 3, {1: update_from_1_to_2})
    with pytest.raises(SchemaVersionError) as excinfo:
        migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one']


def test_migration_invalid_version(migration_cls):
    db = sqlite3.connect(':memory:')
    migration = migration_cls(create_db_2, 2, {})
    migration.migrate(db)
    migration = migration_cls(create_db_1, 1, {})
    with pytest.raises(SchemaVersionError) as excinfo:
        migration.migrate(db)
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']


def test_migration_integrity_error(migration_cls):
    def create_db(db):
        db.execute("CREATE TABLE t (one INTEGER PRIMARY KEY);")
        db.execute(
            "CREATE TABLE u (two INTEGER NOT NULL, FOREIGN KEY (two) REFERENCES t(one));"
        )

    def update_from_1_to_2(db):
        db.execute("INSERT INTO u VALUES (1);")

    db = sqlite3.connect(':memory:')
    db.execute("PRAGMA foreign_keys = ON;")

    migration = migration_cls(create_db, 1, {})
    migration.migrate(db)
    migration = migration_cls(create_db, 2, {1: update_from_1_to_2})
    with pytest.raises(IntegrityError):
        migration.migrate(db)


@pytest.mark.parametrize('version', [-1, []])
def test_migration_version_valuerror(migration_cls, version):
    db = sqlite3.connect(':memory:')
    migration = migration_cls(create_db_1, version, {})
    with pytest.raises(ValueError) as excinfo:
        migration.migrate(db)


def test_old_migration_invalid_version_table():
    # TODO: remove in 2.0
    db = sqlite3.connect(':memory:')
    with db:
        db.execute("CREATE TABLE version (not_version);")
    migration = OldMigration(create_db_2, 2, {})
    with pytest.raises(SchemaVersionError) as excinfo:
        migration.migrate(db)


def test_migration_version_migration():
    """That is, the migration of the migration system from storing
    the schema version in a "version (version INTEGER NOT NULL)" table
    to using "PRAGMA user_version".
    """
    # TODO: remove in 2.0
    db = sqlite3.connect(':memory:')
    with db:
        # emulate a database managed by OldMigration
        db.execute("CREATE TABLE version (version INTEGER NOT NULL);")
        db.execute("INSERT INTO version VALUES (1);")
        create_db_1(db)
    migration = HeavyMigration(create_db_1, 2, {1: update_from_1_to_2})
    migration.migrate(db)

    with pytest.raises(sqlite3.OperationalError) as excinfo:
        db.execute("SELECT * FROM version;")
    assert 'no such table' in str(excinfo.value)

    assert list(db.execute("PRAGMA user_version;")) == [(2,)]

    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']


def test_nonempty(migration_cls):
    db = sqlite3.connect(':memory:')
    db.execute("CREATE TABLE unexpected (one INTEGER);")
    migration = migration_cls(create_db_2, 2, {})
    with pytest.raises(DBError):
        migration.migrate(db)


@rename_argument('migration_cls', 'migration_cls_no_id')
def test_invalid_id(migration_cls):
    db = sqlite3.connect(':memory:')
    db.execute("PRAGMA application_id = 2;")
    migration = migration_cls(create_db_2, 2, {}, id=1)
    with pytest.raises(IdError):
        migration.migrate(db)


@rename_argument('migration_cls', 'migration_cls_no_id')
def test_missing_id_with_version(migration_cls):
    db = sqlite3.connect(':memory:')
    migration_cls.set_version(db, 2)
    migration = migration_cls(create_db_2, 2, {}, id=1)
    with pytest.raises(IdError):
        migration.migrate(db)


@rename_argument('migration_cls', 'migration_cls_no_id')
def test_missing_id_after_migration(migration_cls):
    db = sqlite3.connect(':memory:')

    migration = migration_cls(create_db_1, 1, {})
    migration.migrate(db)

    migration = migration_cls(create_db_2_error, 2, {1: update_from_1_to_2}, id=1)
    with pytest.raises(IdError):
        migration.migrate(db)

    def bad_update_from_1_to_2(db):
        migration_cls.set_id(db, 2)

    migration = migration_cls(create_db_2_error, 2, {1: bad_update_from_1_to_2}, id=1)
    with pytest.raises(IdError):
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
        version=1,
        migrations={},
        id=1234,
        minimum_sqlite_version=(3, 15, 0),
        wal_enabled=wal_enabled,
    )

    ((mode,),) = db.execute("PRAGMA journal_mode;")
    assert mode.lower() == expected_mode
