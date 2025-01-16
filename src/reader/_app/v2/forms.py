import yaml
from wtforms import Form
from wtforms import HiddenField
from wtforms import RadioField
from wtforms import SearchField
from wtforms import StringField

from reader._types import tag_filter_argument


class TagFilterField(StringField):

    def process_formdata(self, valuelist):
        if not valuelist:
            return
        value = valuelist[0]
        if '[' not in value:
            value = f'[{value}]'
        try:
            data = yaml.safe_load(value)
        except yaml.error.MarkedYAMLError as e:
            raise ValueError(f"invalid YAML: {e.problem or e.context}") from e
        tag_filter_argument(data)
        self.data = data

    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        if not self.data:
            return ''
        return yaml.safe_dump(self.data, default_flow_style=True).rstrip()


class ToFormdataMixin:
    def to_formdata(self):
        rv = {}

        for field in self:
            try:
                value = field._value()
            except AttributeError:
                values = [option._value() for option in field if option.checked]
                if values:
                    value, *rest = values
                    if rest:
                        raise NotImplementedError(
                            "multiple choices not supported"
                        ) from None
                else:
                    value = field.default

            if value and value != field.default:
                rv[field.name] = value

        return rv


def radio_field(*args, choices, **kwargs):
    """Like RadioField, but choices is a list of (value, value_str),
    (value, value_str, label), or (value, value_str, label, render_kw) tuples.

    """
    return RadioField(
        *args,
        choices=[c[1] if len(c) == 2 else c[1:] for c in choices],
        coerce={c[1]: c[0] for c in choices}.get,
        **kwargs,
    )


BOOL_CHOICES = [(True, 'yes'), (False, 'no'), (None, 'all')]
TRISTATE_CHOICES = [('notfalse', 'maybe')] + BOOL_CHOICES
ENTRY_SORT_CHOICES = ['recent', 'random']


class EntryFilter(ToFormdataMixin, Form):
    feed = HiddenField("feed")
    search = SearchField("search", name='q')
    feed_tags = TagFilterField("tags", name='tags')
    read = radio_field("read", choices=BOOL_CHOICES, default='no')
    important = radio_field("important", choices=TRISTATE_CHOICES, default='maybe')
    has_enclosures = radio_field(
        "enclosures", name='enclosures', choices=BOOL_CHOICES, default='all'
    )
    sort = RadioField("sort", choices=ENTRY_SORT_CHOICES, default='recent')


class SearchEntryFilter(EntryFilter):
    sort = RadioField(
        "sort", choices=ENTRY_SORT_CHOICES + ['relevant'], default='relevant'
    )


ENTRY_FILTER_PRESETS = {
    'unread': {},
    'important': {'read': 'all', 'important': 'yes'},
    'podcast': {'enclosures': 'yes'},
    'random': {'sort': 'random'},
}


if __name__ == '__main__':
    from werkzeug.datastructures import MultiDict

    args = MultiDict(dict(tags='1'))
    for FormCls in EntryFilter, SearchEntryFilter:
        form = FormCls(args)
        for field in form:
            print(field())
            print()
        print(form.data)
        print(form.to_formdata())
        print()

    print(form.feed_tags.__dict__)
    import IPython

    IPython.embed()
