"""

To run a local development server:

    FLASK_DEBUG=1 FLASK_TRAP_BAD_REQUEST_ERRORS=1 \
    FLASK_APP=src/reader/_app/wsgi.py \
    READER_CONFIG=examples/config.yaml READER_DB=db.sqlite \
    flask run -h 0.0.0.0 -p 8000

"""
import os

import reader._app
import reader._config


# TODO: this if is for compatibility only, remove after config is released
if reader._CONFIG_ENVVAR in os.environ:
    with open(os.environ[reader._CONFIG_ENVVAR]) as file:
        config = reader._config.load_config(file)
else:
    config = reader._config.load_config({'reader': {}, 'app': {}})


# TODO: this is for compatibility only, remove after config is released
user_config = {'reader': {}, 'app': {}}
if reader._DB_ENVVAR in os.environ:
    user_config['reader']['url'] = os.environ[reader._DB_ENVVAR]
user_config['reader']['plugins'] = dict.fromkeys(
    os.environ.get(reader._PLUGIN_ENVVAR, '').split()
)
user_config['app']['plugins'] = dict.fromkeys(
    os.environ.get(reader._APP_PLUGIN_ENVVAR, '').split()
)
for key in 'reader', 'app':
    config[key] = reader._config.merge_config(config[key], user_config[key])


app = reader._app.create_app(config)
app.config['TRAP_BAD_REQUEST_ERRORS'] = bool(
    os.environ.get('FLASK_TRAP_BAD_REQUEST_ERRORS', '')
)
