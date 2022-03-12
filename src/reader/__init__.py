"""
reader
======

A minimal feed reader.

Usage
-----

Here is small example of using reader.

Create a Reader object::

    reader = make_reader('db.sqlite')

Add a feed::

    reader.add_feed('http://www.hellointernet.fm/podcast?format=rss')

Update all the feeds::

    reader.update_feeds()

Get all the entries, both read and unread::

    entries = list(reader.get_entries())

Mark the first entry as read::

    reader.mark_entry_as_read(entries[0])

Print the titles of the unread entries::

    for e in reader.get_entries(read=False):
        print(e.title)


"""

__version__ = '2.10'

from .core import Reader, make_reader

from .types import (
    Feed,
    ExceptionInfo,
    Entry,
    Content,
    Enclosure,
    EntrySearchResult,
    HighlightedString,
    FeedCounts,
    EntryCounts,
    EntrySearchCounts,
    UpdateResult,
    UpdatedFeed,
    EntryUpdateStatus,
)

from .exceptions import (
    ReaderError,
    FeedError,
    FeedExistsError,
    FeedNotFoundError,
    ParseError,
    InvalidFeedURLError,
    EntryError,
    EntryExistsError,
    EntryNotFoundError,
    MetadataError,
    MetadataNotFoundError,
    FeedMetadataNotFoundError,
    StorageError,
    SearchError,
    SearchNotEnabledError,
    InvalidSearchQueryError,
    TagError,
    TagNotFoundError,
    ResourceNotFoundError,
    PluginError,
    InvalidPluginError,
)


# For internal use only.

_CONFIG_ENVVAR = 'READER_CONFIG'
_DB_ENVVAR = 'READER_DB'
_PLUGIN_ENVVAR = 'READER_PLUGIN'
_APP_PLUGIN_ENVVAR = 'READER_APP_PLUGIN'
_CLI_PLUGIN_ENVVAR = 'READER_CLI_PLUGIN'


# Prevent any logging output by default. If no handler is set,
# the messages bubble up to the root logger and get printed on stderr.
# https://docs.python.org/3/howto/logging.html#library-config
import logging  # noqa: E402

logging.getLogger('reader').addHandler(logging.NullHandler())
