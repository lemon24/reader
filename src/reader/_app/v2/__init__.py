from functools import partial

from flask import Blueprint
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
    # TODO: pagination
    # TODO: read time
    # TODO: mark as ...

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
