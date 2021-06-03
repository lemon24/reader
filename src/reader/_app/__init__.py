import contextlib
import itertools
import json
import time
from dataclasses import dataclass

import flask.signals
import humanize
import markupsafe
import yaml
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

blueprint = Blueprint('reader', __name__)

blueprint.app_template_filter('humanize_naturaltime')(humanize.naturaltime)

# if any plugins need signals, they need to install blinker
signals = flask.signals.Namespace()

# NOTE: these signals are part of the app extension API
got_preview_parse_error = signals.signal('preview-parse-error')


def get_reader():
    if not hasattr(g, 'reader'):
        g.reader = current_app.config['READER_CONFIG'].make_reader(
            'app', plugin_loader=current_app.plugin_loader
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
        assert sort in ('relevant', 'recent', 'random')

    reader = get_reader()

    feed_url = request.args.get('feed')
    feed = None
    feed_tags = None
    if feed_url:
        feed = reader.get_feed(feed_url, None)
        if not feed:
            abort(404)
        feed_tags = list(reader.get_feed_tags(feed))

    args = request.args.copy()
    query = args.pop('q', None)
    if query is None:

        def get_entries(**kwargs):
            yield from reader.get_entries(sort=sort, **kwargs)

        get_entry_counts = reader.get_entry_counts

    elif not query:
        # if the query is '', it's not a search
        args.pop('sort', None)
        return redirect(url_for('.entries', **args))

    else:

        def get_entries(**kwargs):
            for sr in reader.search_entries(query, sort=sort, **kwargs):
                yield EntryProxy(sr, reader.get_entry(sr))

        def get_entry_counts(**kwargs):
            return reader.search_entry_counts(query, **kwargs)

    # TODO: render the actual search result, not the entry
    # TODO: catch and flash syntax errors
    # TODO: don't show search box if search is not enabled

    error = None

    # TODO: duplicated from feeds()
    tags_str = tags = args.pop('tags', None)
    if tags is None:
        pass
    elif not tags.strip():
        # if tags is '', it's not a tag filter
        return redirect(url_for('.entries', **args))
    else:

        try:
            tags = yaml.safe_load(tags)
        except yaml.YAMLError as e:
            error = f"invalid tag query: invalid YAML: {e}: {tags_str}"
            return stream_template(
                'entries.html', feed=feed, feed_tags=feed_tags, error=error
            )

    kwargs = dict(
        feed=feed_url,
        read=read,
        has_enclosures=has_enclosures,
        important=important,
        feed_tags=tags,
    )
    entries = get_entries(**kwargs, limit=request.args.get('limit', type=int))

    with_counts = request.args.get('counts')
    with_counts = {None: None, 'no': False, 'yes': True}[with_counts]
    counts = get_entry_counts(**kwargs) if with_counts else None

    try:
        first = next(entries)
        entries = itertools.chain([first], entries)
    except StopIteration:
        pass
    except InvalidSearchQueryError as e:
        error = f"invalid search query: {e}"
    except ValueError as e:
        # TODO: there should be a better way of matching this kind of error
        if 'tag' in str(e).lower():
            error = f"invalid tag query: {e}: {tags_str}"
        else:
            raise

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
        feed_tags=feed_tags,
        entries_data=entries_data,
        error=error,
        counts=counts,
    )


@blueprint.route('/preview')
def preview():
    # TODO: maybe unify with entries() somehow
    url = request.args['url']

    # TODO: maybe redirect to the feed we have if we already have it

    # TODO: maybe cache stuff

    reader = current_app.config['READER_CONFIG'].make_reader(
        'default', url=':memory:', plugin_loader=current_app.plugin_loader
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
    broken = request.args.get('broken')
    broken = {None: None, 'no': False, 'yes': True}[broken]

    updates_enabled = request.args.get('updates-enabled')
    updates_enabled = {None: None, 'no': False, 'yes': True}[updates_enabled]

    sort = request.args.get('sort', 'title')
    assert sort in ('title', 'added')

    error = None

    args = request.args.copy()

    tags_str = tags = args.pop('tags', None)
    if tags is None:
        pass
    elif not tags.strip():
        # if tags is '', it's not a tag filter
        return redirect(url_for('.feeds', **args))
    else:

        try:
            tags = yaml.safe_load(tags)
        except yaml.YAMLError as e:
            error = f"invalid tag query: invalid YAML: {e}: {tags_str}"
            return stream_template('feeds.html', feed_data=[], error=error)

    reader = get_reader()

    kwargs = dict(broken=broken, tags=tags, updates_enabled=updates_enabled)

    with_counts = request.args.get('counts')
    with_counts = {None: None, 'no': False, 'yes': True}[with_counts]
    counts = reader.get_feed_counts(**kwargs) if with_counts else None

    feed_data = []
    try:
        feeds = reader.get_feeds(sort=sort, **kwargs)
        feed_data = (
            (
                feed,
                list(reader.get_feed_tags(feed)),
                reader.get_entry_counts(feed=feed) if with_counts else None,
            )
            for feed in feeds
        )
    except ValueError as e:
        # TODO: there should be a better way of matching this kind of error
        if 'tag' in str(e).lower():
            error = f"invalid tag query: {e}: {tags_str}"
        else:
            raise

    # Ensure flashed messages get removed from the session.
    # https://github.com/lemon24/reader/issues/81
    get_flashed_messages()

    return stream_template(
        'feeds.html', feed_data=feed_data, error=error, counts=counts
    )


@blueprint.route('/metadata')
def metadata():
    reader = get_reader()

    feed_url = request.args['feed']
    feed = reader.get_feed(feed_url, None)
    if not feed:
        abort(404)

    metadata = reader.get_feed_metadata(feed_url)

    # Ensure flashed messages get removed from the session.
    # https://github.com/lemon24/reader/issues/81
    get_flashed_messages()

    return stream_template(
        'metadata.html',
        feed=feed,
        metadata=metadata,
        to_pretty_json=lambda t: yaml.safe_dump(t),
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


@blueprint.route('/tags')
def tags():
    reader = get_reader()

    with_counts = request.args.get('counts')
    with_counts = {None: None, 'no': False, 'yes': True}[with_counts]

    def iter_tags():
        for tag in itertools.chain([None, True, False], reader.get_feed_tags()):
            feed_counts = None
            entry_counts = None

            if with_counts:
                tags_arg = [tag] if tag is not None else tag
                feed_counts = reader.get_feed_counts(tags=tags_arg)
                entry_counts = reader.get_entry_counts(feed_tags=tags_arg)

            yield tag, feed_counts, entry_counts

    return render_template('tags.html', tags=iter_tags())


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
    get_reader().mark_entry_as_read((feed_url, entry_id))


@form_api
@readererror_to_apierror()
def mark_as_unread(data):
    feed_url = data['feed-url']
    entry_id = data['entry-id']
    get_reader().mark_entry_as_unread((feed_url, entry_id))


@form_api(really=True)
@readererror_to_apierror()
def mark_all_as_read(data):
    feed_url = data['feed-url']
    entry_id = json.loads(data['entry-id'])
    for entry_id in entry_id:
        get_reader().mark_entry_as_read((feed_url, entry_id))


@form_api(really=True)
@readererror_to_apierror()
def mark_all_as_unread(data):
    feed_url = data['feed-url']
    entry_id = json.loads(data['entry-id'])
    for entry_id in entry_id:
        get_reader().mark_entry_as_unread((feed_url, entry_id))


@form_api
@readererror_to_apierror()
def mark_as_important(data):
    feed_url = data['feed-url']
    entry_id = data['entry-id']
    get_reader().mark_entry_as_important((feed_url, entry_id))


@form_api
@readererror_to_apierror()
def mark_as_unimportant(data):
    feed_url = data['feed-url']
    entry_id = data['entry-id']
    get_reader().mark_entry_as_unimportant((feed_url, entry_id))


@form_api(really=True)
@readererror_to_apierror()
def delete_feed(data):
    feed_url = data['feed-url']
    get_reader().delete_feed(feed_url)


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
    get_reader().set_feed_metadata_item(feed_url, key, None)


@form_api
@readererror_to_apierror()
def update_metadata(data):
    feed_url = data['feed-url']
    key = data['key']
    try:
        value = yaml.safe_load(data['value'])
    except yaml.YAMLError as e:
        raise APIError("invalid JSON: {}".format(e), (feed_url, key))
    get_reader().set_feed_metadata_item(feed_url, key, value)


@form_api
@readererror_to_apierror()
def delete_metadata(data):
    feed_url = data['feed-url']
    key = data['key']
    get_reader().delete_feed_metadata_item(feed_url, key)


@form_api
@readererror_to_apierror()
def update_feed_tags(data):
    feed_url = data['feed-url']
    feed_tags = set(data['feed-tags'].split())

    reader = get_reader()
    tags = set(reader.get_feed_tags(feed_url))

    for tag in tags - feed_tags:
        reader.remove_feed_tag(feed_url, tag)
    for tag in feed_tags - tags:
        reader.add_feed_tag(feed_url, tag)


@form_api(really=True)
@readererror_to_apierror()
def change_feed_url(data):
    feed_url = data['feed-url']
    new_feed_url = data['new-feed-url'].strip()
    # TODO: when there's a way to validate URLs, use it
    # https://github.com/lemon24/reader/issues/155#issuecomment-673694472
    get_reader().change_feed_url(feed_url, new_feed_url)


@form_api
@readererror_to_apierror()
def enable_feed_updates(data):
    feed_url = data['feed-url']
    get_reader().enable_feed_updates(feed_url)


@form_api
@readererror_to_apierror()
def disable_feed_updates(data):
    feed_url = data['feed-url']
    get_reader().disable_feed_updates(feed_url)


@form_api
@readererror_to_apierror()
def update_feed(data):
    # TODO: feed updates should happen in the background
    # (otherwise we're tying up a worker);
    # acceptable only because /preview does it as well
    feed_url = data['feed-url']
    get_reader().update_feed(feed_url)


# for some reason, @blueprint.app_template_global does not work
@blueprint.app_template_global()
def additional_enclosure_links(enclosure, entry):
    funcs = getattr(current_app, 'reader_additional_enclosure_links', ())
    for func in funcs:
        yield from func(enclosure, entry)


def create_app(config):
    app = Flask(__name__)
    app.secret_key = 'secret'

    app.config['READER_CONFIG'] = config
    app.teardown_appcontext(close_db)

    app.register_blueprint(blueprint)

    # NOTE: this is part of the app extension API
    app.reader_additional_enclosure_links = []

    app.plugin_loader = loader = Loader()

    def log_exception(message, cause):
        app.logger.exception("%s; original traceback follows", message, exc_info=cause)

    # Don't raise exceptions for plugins, just log.
    # Does it make sense to keep going after initializing a plugin fails?
    # How do we know the target isn't left in a bad state?
    loader.handle_import_error = log_exception
    loader.handle_init_error = log_exception

    # Fail fast for reader plugin import/init errors
    # (although depending on the handler they may just be logged).
    with app.app_context():
        get_reader()

    loader.init(app, config.merged('app').get('plugins', {}))

    return app
