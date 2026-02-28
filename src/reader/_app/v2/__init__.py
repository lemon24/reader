import itertools
from functools import partial

from flask import abort
from flask import Blueprint
from flask import current_app
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from jinja2_fragments.flask import render_block

from .. import EntryProxy
from .. import get_reader
from .. import stream_template
from .forms import EntryFilter
from .forms import FeedFilter


# for a prototype with tags and search support, see
# https://github.com/lemon24/reader/tree/3.21/src/reader/_app/v2


blueprint = Blueprint(
    'v2', __name__, template_folder='templates', static_folder='static'
)


@blueprint.route('/')
def entries():
    reader = get_reader()

    form = EntryFilter(request.args)

    feed = None
    if feed_url := form.feed.data:
        feed = reader.get_feed(feed_url, None)
        if not feed:
            abort(404)

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
        'v2/entries.html',
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
            case 'true':
                reader.set_entry_read(entry, True)
            case 'false':
                reader.set_entry_read(entry, False)
            case _:
                abort(422)

    if 'important' in request.form:
        match request.form['important']:
            case 'true':
                reader.set_entry_important(entry, True)
            case 'false':
                reader.set_entry_important(entry, False)
            case 'none':
                reader.set_entry_important(entry, None)
            case _:
                abort(422)

    if request.headers.get('hx-request') == 'true':
        return render_block(
            'v2/entries.html',
            'entry_actions',
            entry=reader.get_entry(entry),
            next=request.form['next'],
            # equivalent to {% import "v2/macros.html" as macros %}
            macros=current_app.jinja_env.get_template('v2/macros.html').module,
        )

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
        'v2/feeds.html',
        form=form,
        feeds=feeds,
    )


@blueprint.route('/feed-actions', methods=['POST'])
def feed_actions():
    reader = get_reader()

    feed = request.form['feed-url']

    if 'enabled' in request.form:
        match request.form['enabled']:
            case 'true':
                reader.enable_feed_updates(feed)
            case 'false':
                reader.disable_feed_updates(feed)
            case _:
                abort(422)

    if request.headers.get('hx-request') == 'true':
        return render_block(
            'v2/feeds.html',
            'feed_actions',
            feed=reader.get_feed(feed),
            next=request.form['next'],
            # equivalent to {% import "v2/macros.html" as macros %}
            macros=current_app.jinja_env.get_template('v2/macros.html').module,
        )

    return redirect(request.form['next'], code=303)


@blueprint.route('/feeds/delete', methods=['GET', 'POST'])
def delete_feed():
    reader = get_reader()

    feed = reader.get_feed(request.args['feed'], None)
    if not feed:
        abort(404)

    if request.method == 'POST':
        reader.delete_feed(feed)
        flash(f"Deleted feed {feed.resolved_title or feed.url}.", 'success')
        return redirect(url_for('.feeds'), code=303)

    return render_template(
        'v2/delete_feed.html',
        feed=feed,
    )


@blueprint.route('/feeds/title', methods=['GET', 'POST'])
def change_feed_title():
    reader = get_reader()

    feed = reader.get_feed(request.args['feed'], None)
    if not feed:
        abort(404)

    if request.method == 'POST':
        title = request.form['title'].strip() or None
        reader.set_feed_user_title(feed, title)
        flash(
            f"Changed title of feed {feed.resolved_title or feed.url}"
            f" to {title or feed.title or feed.url}.",
            'success',
        )
        return redirect(url_for('.entries', feed=feed.url), code=303)

    return render_template(
        'v2/change_feed_title.html',
        feed=feed,
    )
