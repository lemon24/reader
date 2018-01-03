
# FLASK_APP=autoapp.py READER_DB=db.sqlite flask run -h localhost -p 8080

import os

from reader.app import app
from reader.db import open_db
from reader.reader import Reader
from reader.cli import get_default_db_path, DB_ENVVAR

app.reader = Reader(open_db(os.environ.get(DB_ENVVAR, get_default_db_path())))
