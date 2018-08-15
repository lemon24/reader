import os

def test_app_wsgi(monkeypatch, db_path):
    # This assumes no-one else imports reader.app.wsgi.app.
    # Also, further imports will yield the same app from this test.
    monkeypatch.setitem(os.environ, 'READER_DB', db_path)
    from reader.app.wsgi import app

