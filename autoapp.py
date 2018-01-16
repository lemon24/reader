
# FLASK_APP=autoapp.py READER_DB=db.sqlite flask run -h localhost -p 8080

import os

from reader.app import app
from reader.cli import get_default_db_path

app.config['READER_DB'] = os.environ.get('READER_DB', get_default_db_path())
