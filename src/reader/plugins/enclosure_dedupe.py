"""
enclosure_dedupe
~~~~~~~~~~~~~~~~

Deduplicate enclosures of an entry by enclosure URL.

To load::

    READER_PLUGIN='reader.plugins.enclosure_dedupe:enclosure_dedupe' \\
    python -m reader ...

Implemented for https://github.com/lemon24/reader/issues/78.

.. todo::

    There should be a hook for this.

"""

import functools
from collections import OrderedDict


def enclosure_dedupe(reader):
    original_get_entries = reader.get_entries

    @functools.wraps(original_get_entries)
    def get_entries(*args, **kwargs):
        for entry in original_get_entries(*args, **kwargs):
            if entry.enclosures:
                enclosures_by_href = OrderedDict()
                for e in entry.enclosures:
                    enclosures_by_href.setdefault(e.href, e)
                enclosures = tuple(enclosures_by_href.values())
                entry = entry._replace(enclosures=enclosures)
            yield entry

    reader.get_entries = get_entries


