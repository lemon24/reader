from flask import Flask, render_template, current_app, g, request, jsonify
import humanize

from .reader import Reader


app = Flask(__name__)

app.template_filter('humanize_naturaltime')(humanize.naturaltime)


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
    entries = get_reader().get_entries(_unread_only=True)
    return render_template('root.html', entries=entries)


@app.route('/mark-as-read', methods=['POST'])
def mark_as_read():
    response = {}
    try:
        get_reader()._add_entry_tag(request.form['feed'], request.form['entry'], 'read');
    except Exception as e:
        response['error'] = "{}: {}".format(type(e).__name__, e)
    return jsonify(response)

