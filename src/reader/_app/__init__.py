import itertools
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import partial
from urllib.parse import urlparse

import humanize
from flask import abort
from flask import Blueprint
from flask import current_app
from flask import flash
from flask import Flask
from flask import get_flashed_messages
from flask import redirect
from flask import render_template
from flask import render_template_string
from flask import request
from flask import Response
from flask import stream_with_context
from flask import url_for
from flask_wtf.csrf import CSRFError
from flask_wtf.csrf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from jinja2_fragments.flask import render_block
from werkzeug.exceptions import NotFound

from reader import EntryNotFoundError
from reader import FeedExistsError
from reader import FeedNotFoundError
from reader import InvalidFeedURLError
from reader import UpdateError
from reader._plugins import Loader

from .forms import AddFeed
from .forms import ChangeFeedTitle
from .forms import EntryFilter
from .forms import FeedFilter


# for a prototype with tags and search support, see
# https://github.com/lemon24/reader/tree/3.21/src/reader/_app/v2


blueprint = Blueprint('reader', __name__)


@blueprint.errorhandler(FeedNotFoundError)
def handle_feed_not_found(e):
    return NotFound()


@blueprint.errorhandler(EntryNotFoundError)
def handle_entry_not_found(e):
    return NotFound()


@blueprint.errorhandler(CSRFError)
def handle_csrf_error(error):
    if request.headers.get('hx-request') == 'true':
        return render_template_string(CSRF_ERROR_TEMPLATE, error=error), 419
    return error


CSRF_ERROR_TEMPLATE = """\
<ul class="list-unstyled">
  <li class="alert alert-danger">
    {{ error.description }}
    <a href="javascript:document.location.reload()">Refresh</a> and try again.
  </li>
</ul>
"""


@blueprint.route('/')
def entries():
    reader = get_reader()

    form = EntryFilter(request.args)

    feed = None
    if feed_url := form.feed.data:
        feed = reader.get_feed(feed_url)

    kwargs = dict(form.data)

    if not (feed or kwargs.get('starting_after')):
        limit = 64
    else:
        limit = 256

    get_entries = reader.get_entries

    entries = []
    if form.validate():
        entries = get_entries(**kwargs, limit=limit)

    return stream_template(
        'entries.html',
        form=form,
        entries=entries,
        feed=feed,
        limit=limit,
    )


@blueprint.route('/entry-actions', methods=['POST'])
def entry_actions():
    reader = get_reader()

    entry = request.form['feed-url'], request.form['entry-id']

    if 'read' in request.form:
        match request.form['read']:
            case 'read':
                reader.set_entry_read(entry, True)
            case 'unread':
                reader.set_entry_read(entry, False)
            case _:
                abort(422)

    if 'important' in request.form:
        match request.form['important']:
            case 'important':
                reader.set_entry_important(entry, True)
            case 'unimportant':
                reader.set_entry_important(entry, False)
            case 'clear':
                reader.set_entry_important(entry, None)
            case _:
                abort(422)

    if request.headers.get('hx-request') == 'true':
        if urlparse(request.headers['hx-current-url']).path == url_for('.entry'):
            template = 'entry.html'
        else:
            template = 'entries.html'

    if request.headers.get('hx-request') == 'true':
        return render_block(
            template,
            'entry_actions',
            entry=reader.get_entry(entry),
            next=request.form.get('next'),
            # equivalent to {% import "macros.html" as macros %}
            macros=current_app.jinja_env.get_template('macros.html').module,
        )

    # FIXME: doesn't work for entry
    return redirect(request.form['next'], code=303)


@blueprint.route('/feeds')
def feeds():
    reader = get_reader()

    form = FeedFilter(request.args)

    kwargs = dict(form.data)

    feeds = []
    if form.validate():
        feeds = reader.get_feeds(**kwargs)

    return stream_template(
        'feeds.html',
        form=form,
        feeds=feeds,
    )


@blueprint.route('/feed-actions', methods=['POST'])
def feed_actions():
    reader = get_reader()

    feed = request.form['feed-url']

    if 'enabled' in request.form:
        match request.form['enabled']:
            case 'enable':
                reader.enable_feed_updates(feed)
            case 'disable':
                reader.disable_feed_updates(feed)
            case _:
                abort(422)

    if request.headers.get('hx-request') == 'true':
        if urlparse(request.headers['hx-current-url']).path == url_for('.entries'):
            template = 'entries.html'
        else:
            template = 'feeds.html'

        return render_block(
            template,
            'feed_actions',
            feed=reader.get_feed(feed),
            next=request.form.get('next'),
            # equivalent to {% import "macros.html" as macros %}
            macros=current_app.jinja_env.get_template('macros.html').module,
        )

    # FIXME: doesn't work for feed (entries)
    return redirect(request.form['next'], code=303)


@blueprint.route('/feeds/delete', methods=['GET', 'POST'])
def delete_feed():
    reader = get_reader()
    feed = reader.get_feed(request.args['feed'])

    if request.method == 'POST':
        reader.delete_feed(feed)
        flash(f"Deleted feed {feed.resolved_title or feed.url}.", 'success')
        return redirect(url_for('.feeds'), code=303)

    return render_template('delete_feed.html', feed=feed)


@blueprint.route('/feeds/title', methods=['GET', 'POST'])
def change_feed_title():
    reader = get_reader()
    feed = reader.get_feed(request.args['feed'])

    form = ChangeFeedTitle(request.form, title=feed.resolved_title)

    if request.method == 'POST' and form.validate():
        title = form.title.data
        if not title or title == feed.title:
            title = None
        if title == feed.user_title:
            flash("Feed title is unchanged.", 'secondary')
        else:
            reader.set_feed_user_title(feed, title)
            flash(
                f"Changed feed title from {feed.resolved_title or feed.url}"
                f" to {title or feed.title or feed.url}.",
                'success',
            )
        return redirect(url_for('.entries', feed=feed.url), code=303)

    return render_template('change_feed_title.html', form=form, feed=feed)


@blueprint.route('/feeds/add', methods=['GET', 'POST'])
def add_feed():
    reader = get_reader()
    form = AddFeed(request.form)

    if request.method == 'POST' and form.validate():
        url = form.feed.data

        try:
            reader.add_feed(url)
        except InvalidFeedURLError as e:
            form.feed.errors.append(f"invalid feed: {e}")
        except FeedExistsError:
            flash("Feed already exists.", 'secondary')
            return redirect(url_for('.entries', feed=url), code=303)
        else:
            # TODO: updating should be out of band
            try:
                reader.update_feed(url)
            except UpdateError:
                pass
            else:
                flash("Added and updated feed.", 'success')
            return redirect(url_for('.entries', feed=url), code=303)

    return render_template('add_feed.html', form=form)


@blueprint.route('/entry')
def entry():
    reader = get_reader()
    entry = reader.get_entry((request.args['feed'], request.args['entry']))
    return render_template('entry.html', entry=entry)


def stream_template(template_name_or_list, **kwargs):
    # Ensure flashed messages get removed from the session,
    # otherwise they keep adding up and never disappear.
    # Assumes the template will call get_flashed_messages() at some point.
    # https://github.com/lemon24/reader/issues/81
    get_flashed_messages()

    # Ensure the CSRF session token is set.
    # Assumes the template will generate a token at some at some point.
    # https://github.com/pallets-eco/flask-wtf/issues/668
    generate_csrf()

    template = current_app.jinja_env.get_template(template_name_or_list)

    stream = template.stream(**kwargs)
    # TODO: increase to at least 1-2k, like this we have 50% overhead
    stream.enable_buffering(50)

    return Response(stream_with_context(stream))


@blueprint.app_template_filter()
def humanize_naturaltime(dt):
    when = None
    if dt.tzinfo:
        when = datetime.now(tz=timezone.utc)
    try:
        return humanize.naturaltime(dt, when=when)
    except ValueError as e:
        # can happen for 0001-01-01
        if 'year 0 is out of range' not in str(e):
            raise
        return humanize.naturaltime(dt + timedelta(days=1), when=when)


csrf = CSRFProtect()


def get_reader():
    return current_app.reader


def create_app(config):
    app = Flask(__name__)
    app.jinja_env.add_extension('jinja2.ext.do')

    app.secret_key = 'secret'
    csrf.init_app(app)

    app.config['READER_CONFIG'] = config

    app.register_blueprint(blueprint)

    app.plugin_loader = loader = Loader()

    def log_exception(message, cause):
        app.logger.exception("%s; original traceback follows", message, exc_info=cause)

    # Don't raise exceptions for plugins, just log.
    # Does it make sense to keep going after initializing a plugin fails?
    # How do we know the target isn't left in a bad state?
    loader.handle_import_error = log_exception
    loader.handle_init_error = log_exception

    # There's one reader instance per app.
    app.reader = app.config['READER_CONFIG'].make_reader('app', plugin_loader=loader)

    loader.init(app, config.merged('app').get('plugins', {}))

    return app
