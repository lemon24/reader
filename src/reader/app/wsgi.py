"""

To run a local development server:

    FLASK_DEBUG=1 FLASK_TRAP_BAD_REQUEST_ERRORS=1 \
    FLASK_APP=src/reader/app/wsgi.py \
    READER_DB=db.sqlite flask run -h 0.0.0.0 -p 8000

"""

import os

from reader.app import create_app

app = create_app(
    os.environ['READER_DB'],
    os.environ.get('READER_PLUGIN', '').split(),
)
app.config['TRAP_BAD_REQUEST_ERRORS'] = bool(os.environ.get('FLASK_TRAP_BAD_REQUEST_ERRORS', ''))

