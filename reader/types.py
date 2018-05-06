from collections import OrderedDict

import attr


class attrs_namedtuple_compat:

    @classmethod
    def _make(cls, iterable):
        iterable = tuple(iterable)
        if len(iterable) != len(cls.__attrs_attrs__):
            TypeError('Expected %d arguments, got %d' % (len(cls.__attrs_attrs__), len(iterable)))
        return cls(*iterable)

    def _replace(self, **kwargs):
        rv = self._make(
            kwargs.pop(a.name, getattr(self, a.name))
            for a in self.__attrs_attrs__
        )
        if kwargs:
            raise ValueError('Got unexpected field names: %r' % list(kwargs))
        return rv

    def _asdict(self):
        return OrderedDict(
            (a.name, getattr(self, a.name))
            for a in self.__attrs_attrs__
        )


@attr.s(slots=True, frozen=True)
class Feed(attrs_namedtuple_compat):
    url = attr.ib()
    updated = attr.ib(default=None)
    title = attr.ib(default=None)
    link = attr.ib(default=None)
    user_title = attr.ib(default=None)


@attr.s(slots=True, frozen=True)
class Entry(attrs_namedtuple_compat):
    id = attr.ib()
    updated = attr.ib()
    title = attr.ib(default=None)
    link = attr.ib(default=None)
    published = attr.ib(default=None)
    summary = attr.ib(default=None)
    content = attr.ib(default=None)
    enclosures = attr.ib(default=None)
    read = attr.ib(default=False)


@attr.s(slots=True, frozen=True)
class Content(attrs_namedtuple_compat):
    value = attr.ib()
    type = attr.ib(default=None)
    language = attr.ib(default=None)


@attr.s(slots=True, frozen=True)
class Enclosure(attrs_namedtuple_compat):
    href = attr.ib()
    type = attr.ib(default=None)
    length = attr.ib(default=None)


