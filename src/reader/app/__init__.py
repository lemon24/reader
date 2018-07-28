import json
from urllib.parse import urlparse, urljoin
import functools
import contextlib

from flask import Flask, render_template, current_app, g, request, redirect, abort, Blueprint, flash, get_flashed_messages, jsonify, Response, stream_with_context
import werkzeug
import humanize

from reader import Reader, ReaderError


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


def redirect_to_referrer():
    if not request.referrer:
        return "no referrer", 400
    if not is_safe_url(request.referrer):
        return "bad referrer", 400
    return redirect(request.referrer)


def stream_template(template_name_or_list, **kwargs):
    template = current_app.jinja_env.get_template(template_name_or_list)
    stream = template.stream(**kwargs)
    stream.enable_buffering(50)
    return Response(stream_with_context(stream))


@blueprint.route('/')
def entries():
    show = request.args.get('show', 'unread')
    assert show in ('all', 'read', 'unread')

    has_enclosures = request.args.get('has-enclosures')
    has_enclosures = {None: None, 'no': False, 'yes': True}[has_enclosures]

    reader = get_reader()

    feed_url = request.args.get('feed')
    feed = None
    if feed_url:
        feed = reader.get_feed(feed_url)
        if not feed:
            abort(404)

    entries = list(reader.get_entries(which=show, feed=feed_url, has_enclosures=has_enclosures))

    entries_data = None
    if feed_url:
        entries_data = [e.id for e in entries]

    return stream_template('entries.html', entries=entries, feed=feed, entries_data=entries_data)


@blueprint.route('/feeds')
def feeds():
    feeds = get_reader().get_feeds()
    return stream_template('feeds.html', feeds=feeds)


class APIThing:

    def __init__(self, blueprint, rule, endpoint):
        self.actions = {}
        self.really = {}
        blueprint.add_url_rule(rule, endpoint, methods=['POST'], view_func=self.dispatch)

    def dispatch_form(self):
        action = request.form['action']
        func = self.actions.get(action)
        if func is None:
            return "unknown action", 400
        next = request.form.get('next-' + action)
        if next is None:
            next = request.form['next']
        if not is_safe_url(next):
            return "bad next", 400
        if self.really[func]:
            really = request.form.get('really-' + action)
            if really is None:
                really = request.form.get('really')
            target = request.form.get('target')
            if really != 'really':
                category = (action, )
                if target is not None:
                    category += (target, )
                flash("{}: really not checked".format(action), category)
                return redirect_to_referrer()
        try:
            rv = func(request.form)
            flash(rv)
        except APIError as e:
            category = (action, )
            if e.category:
                category += e.category
            flash("{}: {}".format(action, e), category)
            return redirect_to_referrer()
        return redirect(next)

    def dispatch_json(self):
        data = werkzeug.MultiDict(request.get_json())
        action = data['action']
        func = self.actions.get(action)
        if func is None:
            return "unknown action", 400

        try:
            rv = func(data)
            rv = {'ok': rv}
        except APIError as e:
            category = (action, )
            if e.category:
                category += e.category
            rv = {'err': e.message}

        return jsonify(rv)

    def dispatch(self):
        if request.mimetype == 'application/x-www-form-urlencoded':
            return self.dispatch_form()
        if request.mimetype == 'application/json':
            return self.dispatch_json()
        return "bad content type", 400

    def __call__(self, func=None, *, really=False):

        def register(f):
            self.actions[f.__name__.replace('_', '-')] = f
            self.really[f] = really
            return f

        if func is None:
            return register
        return register(func)


class APIError(Exception):

    def __init__(self, message, category=None):
        super().__init__(message)
        self.message = message
        if category is not None:
            if not isinstance(category, tuple):
                category = (category, )
        self.category = category


@blueprint.app_template_global()
def get_flashed_messages_by_prefix(*prefixes):
    messages = get_flashed_messages(with_categories=True)
    rv = []
    for pair in messages:
        category, message = pair
        if not isinstance(category, tuple):
            category = (category, )
        for prefix in prefixes:
            if not isinstance(prefix, tuple):
                prefix = (prefix, )
            category_prefix = category[:len(prefix)]
            if category_prefix == prefix:
                rv.append(message)
    return rv


form_api = APIThing(blueprint, '/form-api', 'form_api')


@contextlib.contextmanager
def readererror_to_apierror(*args):
    try:
        yield
    except ReaderError as e:
        category = None
        if hasattr(e, 'url'):
            category = (e.url, )
            if hasattr(e, 'id'):
                category += (e.id, )
        raise APIError(str(e), category)


@form_api
@readererror_to_apierror()
def mark_as_read(data):
    feed_url = data['feed-url']
    entry_id = data['entry-id']
    get_reader().mark_as_read((feed_url, entry_id))


@form_api
@readererror_to_apierror()
def mark_as_unread(data):
    feed_url = data['feed-url']
    entry_id = data['entry-id']
    get_reader().mark_as_unread((feed_url, entry_id))


@form_api(really=True)
@readererror_to_apierror()
def mark_all_as_read(data):
    feed_url = data['feed-url']
    entry_id = json.loads(data['entry-id'])
    for entry_id in entry_id:
        get_reader().mark_as_read((feed_url, entry_id))


@form_api(really=True)
@readererror_to_apierror()
def mark_all_as_unread(data):
    feed_url = data['feed-url']
    entry_id = json.loads(data['entry-id'])
    for entry_id in entry_id:
        get_reader().mark_as_unread((feed_url, entry_id))


@form_api(really=True)
@readererror_to_apierror()
def delete_feed(data):
    feed_url = data['feed-url']
    get_reader().remove_feed(feed_url)


@form_api
@readererror_to_apierror()
def add_feed(data):
    feed_url = data['feed-url'].strip()
    assert feed_url, "feed-url cannot be empty"
    # TODO: handle FeedExistsError
    get_reader().add_feed(feed_url)


@form_api
@readererror_to_apierror()
def update_feed_title(data):
    feed_url = data['feed-url']
    feed_title = data['feed-title'].strip() or None
    get_reader().set_feed_user_title(feed_url, feed_title)



def create_app(db_path):
    app = Flask(__name__)
    app.config['READER_DB'] = db_path
    app.secret_key = 'secret'
    app.teardown_appcontext(close_db)

    from .enclosure_tags import enclosure_tags_blueprint, enclosure_tags_filter
    try:
        import mutagen
        import requests
        app.register_blueprint(enclosure_tags_blueprint)
    except ImportError:
        pass
    blueprint.app_template_filter('enclosure_tags')(enclosure_tags_filter)

    app.register_blueprint(blueprint)
    return app

