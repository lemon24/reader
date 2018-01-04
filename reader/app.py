from flask import Flask, render_template, current_app, g
from flask_humanize import Humanize

from .reader import Reader


app = Flask(__name__)
humanize = Humanize(app)


def get_reader():
    if not hasattr(g, 'reader'):
        g.reader = Reader(current_app.config['READER_DB'])
    return g.reader


@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'reader'):
        g.reader.db.close()


@app.route('/')
def root():
    entries = get_reader().get_entries()
    return render_template('root.html', entries=entries)


