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

    """Data type representing a feed."""

    #: The URL of the feed.
    url = attr.ib()

    #: The date the feed was last updated.
    updated = attr.ib(default=None)

    #: The title of the feed.
    title = attr.ib(default=None)

    #: The URL of a page associated with the feed.
    link = attr.ib(default=None)

    #: The author of the feed.
    author = attr.ib(default=None)

    #: User-defined feed title.
    user_title = attr.ib(default=None)


@attr.s(slots=True, frozen=True)
class Entry(attrs_namedtuple_compat):

    """Data type representing an entry."""

    #: Entry identifier.
    id = attr.ib()

    #: The date the entry was last updated.
    updated = attr.ib()

    #: The title of the entry.
    title = attr.ib(default=None)

    #: The URL of a page associated with the entry.
    link = attr.ib(default=None)

    #: The author of the feed.
    author = attr.ib(default=None)

    #: The date the entry was first published.
    published = attr.ib(default=None)

    #: A summary of the entry.
    summary = attr.ib(default=None)

    #: Full content of the entry.
    #: An iterable of :class:`Content` objects.
    content = attr.ib(default=None)

    #: External files associated with the entry.
    #: An iterable of :class:`Enclosure` objects.
    enclosures = attr.ib(default=None)

    #: Whether the entry was read or not.
    read = attr.ib(default=False)

    #: The entry's feed.
    feed = attr.ib(default=None)


@attr.s(slots=True, frozen=True)
class Content(attrs_namedtuple_compat):

    """Data type representing a piece of content."""

    #: The content value.
    value = attr.ib()

    #: The content type.
    type = attr.ib(default=None)

    #: The content language.
    language = attr.ib(default=None)


@attr.s(slots=True, frozen=True)
class Enclosure(attrs_namedtuple_compat):

    """Data type representing an external file."""

    #: The file URL.
    href = attr.ib()

    #: The file content type.
    type = attr.ib(default=None)

    #: The file length.
    length = attr.ib(default=None)


