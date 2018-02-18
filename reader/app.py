import json
from urllib.parse import urlparse, urljoin

from flask import Flask, render_template, current_app, g, request, redirect, abort
import humanize

from . import Reader


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
    show = request.args.get('show', 'unread')
    assert show in ('all', 'read', 'unread')

    reader = get_reader()

    feed_url = request.args.get('feed')
    feed = None
    if feed_url:
        feed = reader.get_feed(feed_url)
        if not feed:
            abort(404)

    entries = list(reader.get_entries(which=show, feed_url=feed_url))

    entries_data = None
    if feed_url:
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
        get_reader().mark_as_read(entry_id['feed'], entry_id['entry'])
        return redirect(next)
    if action == 'mark-as-unread':
        get_reader().mark_as_unread(entry_id['feed'], entry_id['entry'])
        return redirect(next)
    return "unknown action", 400


@app.route('/update-entries', methods=['POST'])
def update_entries():
    action = request.form['action']
    entry_id = json.loads(request.form['entry-id'])
    next = request.form['next']
    if not is_safe_url(next):
        return "bad next", 400
    really = request.form.get('really')
    if really != 'really':
        return "really not checked", 400
    if action == 'mark-all-as-read':
        for entry_id in entry_id:
            get_reader().mark_as_read(entry_id['feed'], entry_id['entry'])
        return redirect(next)
    if action == 'mark-all-as-unread':
        for entry_id in entry_id:
            get_reader().mark_as_unread(entry_id['feed'], entry_id['entry'])
        return redirect(next)
    return "unknown action", 400


@app.route('/feeds')
def feeds():
    feeds = get_reader().get_feeds()
    return render_template('feeds.html', feeds=feeds)

