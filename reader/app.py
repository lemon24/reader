import json
from urllib.parse import urlparse, urljoin

from flask import Flask, render_template, current_app, g, request, redirect, abort, Blueprint, flash
import humanize

from . import Reader, ReaderError


blueprint = Blueprint('reader', __name__)

blueprint.app_template_filter('humanize_naturaltime')(humanize.naturaltime)


def get_reader():
    if not hasattr(g, 'reader'):
        g.reader = Reader(current_app.config['READER_DB'])
    return g.reader

def close_db(error):
    if hasattr(g, 'reader'):
        g.reader.db.close()


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


@blueprint.route('/')
def entries():
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
        entries_data = [e.id for f, e in entries]

    return render_template('entries.html', entries=entries, feed=feed, entries_data=entries_data)


@blueprint.route('/feeds')
def feeds():
    feeds = get_reader().get_feeds()
    return render_template('feeds.html', feeds=feeds)


class APIThing:

    def __init__(self, blueprint, rule, endpoint):
        self.actions = {}
        self.really = {}
        blueprint.add_url_rule(rule, endpoint, methods=['POST'], view_func=self.dispatch)

    def dispatch(self):
        action = request.form['action']
        func = self.actions.get(action)
        if func is None:
            return "unknown action", 400
        next = request.form['next']
        if not is_safe_url(next):
            return "bad next", 400
        if self.really[func]:
            really = request.form.get('really')
            if really != 'really':
                flash("really not checked")
                return redirect(next)
        try:
            func()
        except ReaderError as e:
            flash("error: {}".format(e))
            return redirect(next)
        return redirect(next)

    def __call__(self, func=None, *, really=False):

        def register(f):
            self.actions[f.__name__.replace('_', '-')] = f
            self.really[f] = really
            return f

        if func is None:
            return register
        return register(func)


update_entry = APIThing(blueprint, '/update-entry', 'update_entry')


@update_entry
def mark_as_read():
    feed_url = request.form['feed-url']
    entry_id = request.form['entry-id']
    get_reader().mark_as_read(feed_url, entry_id)


@update_entry
def mark_as_unread():
    feed_url = request.form['feed-url']
    entry_id = request.form['entry-id']
    get_reader().mark_as_unread(feed_url, entry_id)


update_entries = APIThing(blueprint,'/update-entries', 'update_entries')


@update_entries(really=True)
def mark_all_as_read():
    feed_url = request.form['feed-url']
    entry_id = json.loads(request.form['entry-id'])
    for entry_id in entry_id:
        get_reader().mark_as_read(feed_url, entry_id)


@update_entries(really=True)
def mark_all_as_unread():
    feed_url = request.form['feed-url']
    entry_id = json.loads(request.form['entry-id'])
    for entry_id in entry_id:
        get_reader().mark_as_unread(feed_url, entry_id)


@update_entries(really=True)
def delete_feed():
    feed_url = request.form['feed-url']
    get_reader().remove_feed(feed_url)


add_feed = APIThing(blueprint, '/add_feed', 'add_feed')


@add_feed
def add_feed():
    feed_url = request.form['feed-url'].strip()
    assert feed_url, "feed-url cannot be empty"
    # TODO: handle FeedExistsError
    get_reader().add_feed(feed_url)


def create_app(db_path):
    app = Flask(__name__)
    app.config['READER_DB'] = db_path
    app.secret_key = 'secret'
    app.teardown_appcontext(close_db)
    app.register_blueprint(blueprint)
    return app

