import json
from urllib.parse import urlparse, urljoin

from flask import Flask, render_template, current_app, g, request, redirect
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


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


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


@app.route('/update-entry', methods=['POST'])
def update_entry():
    action = request.form['action']
    entry_id = json.loads(request.form['entry-id'])
    next = request.form['next']
    if not is_safe_url(next):
        return "bad next", 400
    if action == 'mark-as-read':
        get_reader().add_entry_tag(entry_id['feed'], entry_id['entry'], 'read')
        return redirect(next)
    else:
        return "unknown action", 400

