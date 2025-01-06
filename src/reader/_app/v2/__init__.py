from functools import partial

from flask import abort
from flask import Blueprint
from flask import redirect
from flask import request

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
    # TODO: if search/tags is active, search/tags box should not be hidden
    # TODO: highlight active filter preset + uncollapse more
    # TODO: feed filter
    # TODO: paqgination
    # TODO: read time
    # TODO: htmx mark as ...

    form = EntryFilter(request.args)
    kwargs = dict(form.data)
    del kwargs['search']

    get_entries = reader.get_entries

    if form.validate():
        entries = get_entries(**kwargs, limit=64)
    else:
        entries = []

    return stream_template(
        'v2/entries.html', presets=ENTRY_FILTER_PRESETS, form=form, entries=entries
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

    print(request.form['next'])
    return redirect(request.form['next'], code=303)
