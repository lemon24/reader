"""

To run a local development server:

    FLASK_DEBUG=1 FLASK_TRAP_BAD_REQUEST_ERRORS=1 \
    FLASK_APP=src/reader/_app/wsgi.py \
    READER_CONFIG=examples/config.yaml READER_DB=db.sqlite \
    flask run -h 0.0.0.0 -p 8000

"""
import os

import yaml

import reader._app
import reader._config


# TODO: the other envvars except _CONFIG_ENVVAR are for compatibility only

if reader._CONFIG_ENVVAR in os.environ:
    with open(os.environ[reader._CONFIG_ENVVAR]) as file:
        config = reader._config.make_reader_config(yaml.safe_load(file))
else:
    config = reader._config.make_reader_config({})

if reader._DB_ENVVAR in os.environ:
    config.all['reader']['url'] = os.environ[reader._DB_ENVVAR]
if reader._PLUGIN_ENVVAR in os.environ:
    config.all['reader']['plugins'] = dict.fromkeys(
        os.environ[reader._PLUGIN_ENVVAR].split()
    )
if reader._APP_PLUGIN_ENVVAR in os.environ:
    config.data['app']['plugins'] = dict.fromkeys(
        os.environ[reader._APP_PLUGIN_ENVVAR].split()
    )

app = reader._app.create_app(config)
app.config['TRAP_BAD_REQUEST_ERRORS'] = bool(
    os.environ.get('FLASK_TRAP_BAD_REQUEST_ERRORS', '')
)
