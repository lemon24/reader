"""
Mark added entries of specific feeds as read if their title matches a regex.

To run:

    READER_DB=db.sqlite \
    READER_PLUGIN='reader.plugins.regex_mark_as_read:regex_mark_as_read' \
    READER_PLUGIN_REGEX_MARK_AS_READ_CONFIG='examples/regex_mark_as_read_config.json' \
    python -m reader update -v

READER_PLUGIN_REGEX_MARK_AS_READ_CONFIG should be a JSON file like:

    {
        "feed-url": [
            "first-regex",
            "second-regex"
        ]
    }

"""

import os
import re
import json


class RegexMarkAsReadPlugin:

    def __init__(self, config):
        self.config = config

    def __call__(self, reader, feed, entry):
        config = self.config.get(feed.url)
        if not config:
            return
        for pattern in config:
            if re.search(pattern, entry.title):
                reader.mark_as_read((feed.url, entry.id))
                return


def regex_mark_as_read(reader):
    with open(os.environ['READER_PLUGIN_REGEX_MARK_AS_READ_CONFIG']) as f:
        config = json.load(f)
    plugin = RegexMarkAsReadPlugin(config)
    reader._post_entry_add_plugins.append(plugin)


