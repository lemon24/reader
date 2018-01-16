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

    feed_url = request.args.get('feed')
    feed = None
    entries_data = None
    if feed_url:
        entries = [(f, e) for f, e in entries if f.url == feed_url]
        try:
            feed = entries[0][0]
        except IndexError:
            return "Unknown feed (or has no entries): {}".format(feed_url), 404
        entries_data = [{'feed': f.url, 'entry': e.id} for f, e in entries]

    return render_template('root.html', entries=entries, feed=feed, entries_data=entries_data)


@app.route('/mark-as-read', methods=['POST'])
def mark_as_read():
    response = {}
    try:
        get_reader().add_entry_tag(request.form['feed'], request.form['entry'], 'read');
    except Exception as e:
        response['error'] = "{}: {}".format(type(e).__name__, e)
    return jsonify(response)

