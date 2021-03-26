"""
reader.enclosure_dedupe
~~~~~~~~~~~~~~~~~~~~~~~

Deduplicate the enclosures of an entry by enclosure URL.

.. todo::

    There should be a hook for this.

..
    Implemented for https://github.com/lemon24/reader/issues/78.

"""
import functools


def init_reader(reader):
    get_entries = reader.get_entries

    @functools.wraps(get_entries)
    def wrapper(*args, **kwargs):
        for entry in get_entries(*args, **kwargs):
            if entry.enclosures:

                enclosures_by_href = {}
                for e in entry.enclosures:
                    enclosures_by_href.setdefault(e.href, e)

                enclosures = tuple(enclosures_by_href.values())
                entry = entry._replace(enclosures=enclosures)

            yield entry

    reader.get_entries = wrapper
