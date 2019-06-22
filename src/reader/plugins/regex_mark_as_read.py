"""
regex_mark_as_read
~~~~~~~~~~~~~~~~~~

Mark added entries of specific feeds as read if their title matches a regex.

To load::

    READER_PLUGIN='reader.plugins.regex_mark_as_read:regex_mark_as_read' \\
    python -m reader update -v

To configure, set the ``regex-mark-as-read`` feed metadata to something like
this::

    {
        "patterns": ["first-regex", "second-regex"]
    }

Implemented for https://github.com/lemon24/reader/issues/79.

.. todo::

    Possible optimizations:

    1.  Add the entry directly as read instead of marking it afterwards
        (requires a new hook to process the entry before it is added,
        and Storage support).

"""
import os
import re


def plugin(reader, url, entry):
    config = reader.get_feed_metadata(url, 'regex-mark-as-read', {}).get('patterns')
    if not config:
        return
    for pattern in config:
        if re.search(pattern, entry.title):
            reader.mark_as_read((url, entry.id))
            return


def regex_mark_as_read(reader):
    reader._post_entry_add_plugins.append(plugin)
