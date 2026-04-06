"""

To run a local development server:

    FLASK_DEBUG=1 FLASK_TRAP_BAD_REQUEST_ERRORS=1 \
    FLASK_APP=src/reader/_app/wsgi.py \
    READER_CONFIG=examples/config.toml READER_DB=db.sqlite \
    flask run -h 0.0.0.0 -p 8000

"""

import logging
import os

import reader._app
import reader._cli

config = reader._cli.load_reader_config()
app = reader._app.create_app(config)
app.config['TRAP_BAD_REQUEST_ERRORS'] = bool(
    os.environ.get('FLASK_TRAP_BAD_REQUEST_ERRORS', '')
)

if not app.debug:
    logging.basicConfig(
        format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    )
