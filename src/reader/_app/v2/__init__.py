from functools import partial

from flask import abort
from flask import Blueprint
from flask import current_app
from flask import redirect
from flask import request
from jinja2_fragments.flask import render_block

from .. import get_reader
from .. import stream_template
from .forms import ENTRY_FILTER_PRESETS
from .forms import EntryFilter


blueprint = Blueprint(
    'v2', __name__, template_folder='templates', static_folder='static'
)


@blueprint.route('/')
def entries():
    reader = get_reader()

    # TODO: search
    # TODO: highlight active filter preset + uncollapse more
    # TODO: paqgination
    # TODO: read time

    form = EntryFilter(request.args)
    kwargs = dict(form.data)
    del kwargs['search']

    feed = None
    if form.feed.data:
        feed = reader.get_feed(form.feed.data, None)
        if not feed:
            abort(404)

    get_entries = reader.get_entries

    if form.validate():
        entries = get_entries(**kwargs, limit=64)
    else:
        entries = []

    return stream_template(
        'v2/entries.html',
        presets=ENTRY_FILTER_PRESETS,
        form=form,
        entries=entries,
        feed=feed,
    )


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
