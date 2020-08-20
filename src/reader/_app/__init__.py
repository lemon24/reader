import contextlib
import itertools
import json
import time
from dataclasses import dataclass

import flask.signals
import humanize
import markupsafe
from flask import abort
from flask import Blueprint
from flask import current_app
from flask import flash
from flask import Flask
from flask import g
from flask import get_flashed_messages
from flask import redirect
from flask import render_template
from flask import request
from flask import Response
from flask import stream_with_context
from flask import url_for

import reader
from .api_thing import APIError
from .api_thing import APIThing
from reader import Content
from reader import Entry
from reader import EntrySearchResult
from reader import InvalidSearchQueryError
from reader import ParseError
from reader import ReaderError
from reader._plugins import Loader
from reader._plugins import LoaderError

blueprint = Blueprint('reader', __name__)

blueprint.app_template_filter('humanize_naturaltime')(humanize.naturaltime)

# if any plugins need signals, they need to install blinker
signals = flask.signals.Namespace()

# NOTE: these signals are part of the app extension API
got_preview_parse_error = signals.signal('preview-parse-error')


def get_reader():
    if not hasattr(g, 'reader'):
        g.reader = current_app.config['READER_CONFIG'].make_reader(
            'app', plugin_loader_cls=FlaskPluginLoader
        )
    return g.reader


def close_db(error):
    if hasattr(g, 'reader'):
        g.reader.close()


def stream_template(template_name_or_list, **kwargs):
    template = current_app.jinja_env.get_template(template_name_or_list)
    stream = template.stream(**kwargs)
    stream.enable_buffering(50)
    return Response(stream_with_context(stream))


@blueprint.before_app_request
def add_request_time():
    start = time.monotonic()
    g.request_time = lambda: time.monotonic() - start


@blueprint.before_app_request
def add_reader_version():
    g.reader_version = reader.__version__


def highlighted(string):
    # needs to be marked as safe so we don't need to do it everywhere in the template
    # TODO: maybe use something "more semantic" than <b> (CSS needs changing too if so)
    return markupsafe.Markup(
        string.apply('<b>', '</b>', lambda s: str(markupsafe.escape(s)))
    )


@dataclass(frozen=True)
class EntryProxy:
    _search_result: EntrySearchResult
    _entry: Entry

    def __getattr__(self, name):
        return getattr(self._entry, name)

    @property
    def title(self):
        highlight = self._search_result.metadata.get('.title')
        if highlight:
            return str(highlight)
        return None

    @property
    def feed(self):
        return FeedProxy(self._search_result, self._entry)

    @property
    def summary(self):
        highlight = self._search_result.content.get('.summary')
        if highlight:
            return highlighted(highlight)
        return None

    @property
    def content(self):
        rv = []
        for path, highlight in self._search_result.content.items():
            # TODO: find a more correct way to match .content[0].value
            if path.startswith('.content[') and path.endswith('].value'):
                rv.append(Content(str(highlight), 'text/plain'))
                rv.append(Content(highlighted(highlight), 'text/html'))
        return rv


@dataclass(frozen=True)
class FeedProxy:
    _search_result: EntrySearchResult
    _entry: Entry

    def __getattr__(self, name):
        return getattr(self._entry.feed, name)

    @property
    def title(self):
        highlight = self._search_result.metadata.get('.feed.title')
        if highlight:
            return str(highlight)
        return self._entry.feed.title


@blueprint.route('/')
def entries():
    show = request.args.get('show', 'unread')
    read = {'all': None, 'unread': False, 'read': True}[show]

    has_enclosures = request.args.get('has-enclosures')
    has_enclosures = {None: None, 'no': False, 'yes': True}[has_enclosures]

    important = request.args.get('important')
    important = {None: None, 'no': False, 'yes': True}[important]

    if not request.args.get('q'):
        sort = request.args.get('sort', 'recent')
        assert sort in ('recent', 'random')
    else:
        sort = request.args.get('sort', 'relevant')
        assert sort in ('recent', 'relevant')

    reader = get_reader()

    feed_url = request.args.get('feed')
    feed = None
    if feed_url:
        feed = reader.get_feed(feed_url, None)
        if not feed:
            abort(404)

    args = request.args.copy()
    query = args.pop('q', None)
    if query is None:

        def get_entries(**kwargs):
            yield from reader.get_entries(sort=sort, **kwargs)

    elif not query:
        # if the query is '', it's not a search
        args.pop('sort', None)
        return redirect(url_for('.entries', **args))

    else:

        def get_entries(**kwargs):
            for sr in reader.search_entries(query, sort=sort, **kwargs):
                yield EntryProxy(sr, reader.get_entry(sr))

    # TODO: render the actual search result, not the entry
    # TODO: catch and flash syntax errors
    # TODO: don't show search box if search is not enabled

    entries = get_entries(
        read=read, feed=feed_url, has_enclosures=has_enclosures, important=important
    )

    error = None
    try:
        first = next(entries)
        entries = itertools.chain([first], entries)
    except StopIteration:
        pass
    except InvalidSearchQueryError as e:
        error = f"invalid search query: {e}"

    limit = request.args.get('limit', type=int)
    if limit:
        entries = itertools.islice(entries, limit)

    entries = list(entries)

    entries_data = None
    if feed_url:
        entries_data = [e.id for e in entries]

    # Ensure flashed messages get removed from the session,
    # otherwise they keep adding up and never disappear.
    # Assumes the template will call get_flashed_messages() at some point.
    # https://github.com/lemon24/reader/issues/81
    get_flashed_messages()

    return stream_template(
        'entries.html',
        entries=entries,
        feed=feed,
        entries_data=entries_data,
        error=error,
    )


@blueprint.route('/preview')
def preview():
    # TODO: maybe unify with entries() somehow
    url = request.args['url']

    # TODO: maybe redirect to the feed we have if we already have it

    # TODO: maybe cache stuff

    reader = current_app.config['READER_CONFIG'].make_reader(
        'default', url=':memory:', plugin_loader_cls=FlaskPluginLoader
    )

    reader.add_feed(url)

    try:
        reader.update_feed(url)
    except ParseError as e:
        # give plugins a chance to intercept this
        got_preview_parse_error.send(e)

    # https://github.com/lemon24/reader/issues/172
    # no plugin intercepted the response, so we show the feed;
    # feed.last_exception will be checked in the template,
    # and if there was a ParseError, it will be shown

    feed = reader.get_feed(url)
    entries = list(reader.get_entries())

    # TODO: maybe limit
    return stream_template('entries.html', entries=entries, feed=feed, read_only=True)


@blueprint.route('/feeds')
def feeds():
    sort = request.args.get('sort', 'title')
    assert sort in ('title', 'added')

    feeds = get_reader().get_feeds(sort=sort)

    # Ensure flashed messages get removed from the session.
    # https://github.com/lemon24/reader/issues/81
    get_flashed_messages()

    return stream_template('feeds.html', feeds=feeds)


@blueprint.route('/metadata')
def metadata():
    reader = get_reader()

    feed_url = request.args['feed']
    feed = reader.get_feed(feed_url, None)
    if not feed:
        abort(404)

    metadata = reader.iter_feed_metadata(feed_url)

    # Ensure flashed messages get removed from the session.
    # https://github.com/lemon24/reader/issues/81
    get_flashed_messages()

    return stream_template(
        'metadata.html',
        feed=feed,
        metadata=metadata,
        to_pretty_json=lambda t: json.dumps(t, sort_keys=True, indent=4),
    )


@blueprint.route('/entry')
def entry():
    reader = get_reader()

    feed_url = request.args['feed']
    entry_id = request.args['entry']

    entry = reader.get_entry((feed_url, entry_id), default=None)
    if not entry:
        abort(404)

    return render_template('entry.html', entry=entry)


form_api = APIThing(blueprint, '/form-api', 'form_api')


@contextlib.contextmanager
def readererror_to_apierror(*args):
    try:
        yield
    except ReaderError as e:
        category = None
        if hasattr(e, 'url'):
            category = (e.url,)
            if hasattr(e, 'id'):
                category += (e.id,)
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


@form_api
@readererror_to_apierror()
def mark_as_important(data):
    feed_url = data['feed-url']
    entry_id = data['entry-id']
    get_reader().mark_as_important((feed_url, entry_id))


@form_api
@readererror_to_apierror()
def mark_as_unimportant(data):
    feed_url = data['feed-url']
    entry_id = data['entry-id']
    get_reader().mark_as_unimportant((feed_url, entry_id))


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


@form_api
@readererror_to_apierror()
def add_metadata(data):
    feed_url = data['feed-url']
    key = data['key']
    get_reader().set_feed_metadata(feed_url, key, None)


@form_api
@readererror_to_apierror()
def update_metadata(data):
    feed_url = data['feed-url']
    key = data['key']
    try:
        value = json.loads(data['value'])
    except json.JSONDecodeError as e:
        raise APIError("invalid JSON: {}".format(e), (feed_url, key))
    get_reader().set_feed_metadata(feed_url, key, value)


@form_api
@readererror_to_apierror()
def delete_metadata(data):
    feed_url = data['feed-url']
    key = data['key']
    get_reader().delete_feed_metadata(feed_url, key)


# for some reason, @blueprint.app_template_global does not work
@blueprint.app_template_global()
def additional_enclosure_links(enclosure, entry):
    funcs = getattr(current_app, 'reader_additional_enclosure_links', ())
    for func in funcs:
        yield from func(enclosure, entry)


class FlaskPluginLoader(Loader):
    def handle_error(self, exception, cause):
        current_app.logger.exception(
            "%s; original traceback follows", exception, exc_info=cause or exception
        )


def create_app(config):
    app = Flask(__name__)
    app.secret_key = 'secret'

    app.config['READER_CONFIG'] = config
    app.teardown_appcontext(close_db)

    # Force reader plugins to load, so we can fail fast for import errors
    # (although some errors may just be logged while we use FlaskPluginLoader).
    with app.app_context():
        get_reader()

    app.register_blueprint(blueprint)

    # NOTE: this is part of the app extension API
    app.reader_additional_enclosure_links = []

    # app_context() needed for logging to work.
    with app.app_context():
        FlaskPluginLoader(config.merged('app').get('plugins', {})).load_plugins(app)

    return app
