import sqlite3

from reader.db import ddl_transaction


def test_ddl_transaction_ok():
    db = sqlite3.connect(':memory:')
    db.execute("CREATE TABLE t (one INTEGER);")
    with ddl_transaction(db):
        db.execute("ALTER TABLE t ADD COLUMN two INTEGER;")
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one', 'two']


def test_ddl_transaction_fail():
    db = sqlite3.connect(':memory:')
    db.execute("CREATE TABLE t (one INTEGER);")
    try:
        with ddl_transaction(db):
            db.execute("ALTER TABLE t ADD COLUMN two INTEGER;")
            db.execute("ALTER TABLE thisdhouldfail ADD COLUMN two INTEGER;")
    except sqlite3.OperationalError:
        pass
    columns = [r[1] for r in db.execute("PRAGMA table_info(t);")]
    assert columns == ['one']



