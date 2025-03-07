import itertools
from functools import partial

from flask import abort
from flask import Blueprint
from flask import current_app
from flask import redirect
from flask import request
from flask import url_for
from jinja2_fragments.flask import render_block

from reader import InvalidSearchQueryError

from .. import EntryProxy
from .. import get_reader
from .. import stream_template
from .forms import EntryFilter
from .forms import SearchEntryFilter


blueprint = Blueprint(
    'v2', __name__, template_folder='templates', static_folder='static'
)


@blueprint.route('/')
def entries():
    reader = get_reader()

    # TODO: search improvements
    # TODO: paqgination
    # TODO: read time

    if request.args.get('q', '').strip():
        form = SearchEntryFilter(request.args)
    else:
        form = EntryFilter(request.args)

    form_args = form.args
    if q := form_args.pop('Q', ''):
        form_args['q'] = q
        return redirect(url_for('.entries', **form_args))
    if form_args != request.args.to_dict():
        return redirect(url_for('.entries', **form_args))

    feed = None
    if form.feed.data:
        feed = reader.get_feed(form.feed.data, None)
        if not feed:
            abort(404)

    kwargs = dict(form.data)
    if query := kwargs.pop('search', None):

        def get_entries(**kwargs):
            for sr in reader.search_entries(query, **kwargs):
                yield EntryProxy(sr, reader.get_entry(sr))

    else:
        get_entries = reader.get_entries

    entries = []
    if form.validate():
        try:
            entries = eager_iterator(get_entries(**kwargs, limit=64))
        except StopIteration:
            pass
        except InvalidSearchQueryError as e:
            form.search.errors.append(f"invalid query: {e}")

    return stream_template(
        'v2/entries.html',
        form=form,
        entries=entries,
        feed=feed,
    )


def eager_iterator(it):
    it = iter(it)
    try:
        return itertools.chain([next(it)], it)
    except StopIteration:
        return it


@blueprint.route('/mark-as', methods=['POST'])
def mark_as():
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
            'entry_form',
            entry=reader.get_entry(entry),
            next=request.form['next'],
            # equivalent to {% import "v2/macros.html" as macros %}
            macros=current_app.jinja_env.get_template('v2/macros.html').module,
        )

    return redirect(request.form['next'], code=303)
