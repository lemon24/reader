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

__version__ = '3.18'

# isort: off

from .core import (
    Reader as Reader,
    make_reader as make_reader,
)

from .types import (
    Feed as Feed,
    ExceptionInfo as ExceptionInfo,
    Entry as Entry,
    Content as Content,
    Enclosure as Enclosure,
    EntrySource as EntrySource,
    EntrySearchResult as EntrySearchResult,
    HighlightedString as HighlightedString,
    FeedCounts as FeedCounts,
    EntryCounts as EntryCounts,
    EntrySearchCounts as EntrySearchCounts,
    FeedSort as FeedSort,
    EntrySort as EntrySort,
    EntrySearchSort as EntrySearchSort,
    UpdateResult as UpdateResult,
    UpdatedFeed as UpdatedFeed,
    EntryUpdateStatus as EntryUpdateStatus,
)

from .exceptions import (
    ReaderError as ReaderError,
    FeedError as FeedError,
    FeedExistsError as FeedExistsError,
    FeedNotFoundError as FeedNotFoundError,
    InvalidFeedURLError as InvalidFeedURLError,
    EntryError as EntryError,
    EntryExistsError as EntryExistsError,
    EntryNotFoundError as EntryNotFoundError,
    UpdateError as UpdateError,
    ParseError as ParseError,
    UpdateHookError as UpdateHookError,
    SingleUpdateHookError as SingleUpdateHookError,
    UpdateHookErrorGroup as UpdateHookErrorGroup,
    StorageError as StorageError,
    SearchError as SearchError,
    SearchNotEnabledError as SearchNotEnabledError,
    InvalidSearchQueryError as InvalidSearchQueryError,
    TagError as TagError,
    TagNotFoundError as TagNotFoundError,
    ResourceNotFoundError as ResourceNotFoundError,
    PluginError as PluginError,
    InvalidPluginError as InvalidPluginError,
    PluginInitError as PluginInitError,
    ReaderWarning as ReaderWarning,
)


# For internal use only.

_CONFIG_ENVVAR = 'READER_CONFIG'
_DB_ENVVAR = 'READER_DB'
_PLUGIN_ENVVAR = 'READER_PLUGIN'
_APP_PLUGIN_ENVVAR = 'READER_APP_PLUGIN'
_CLI_PLUGIN_ENVVAR = 'READER_CLI_PLUGIN'


# Constants.

USER_AGENT = f'python-reader/{__version__} (+https://github.com/lemon24/reader)'


# Prevent any logging output by default. If no handler is set,
# the messages bubble up to the root logger and get printed on stderr.
# https://docs.python.org/3/howto/logging.html#library-config
import logging  # noqa: E402

logging.getLogger('reader').addHandler(logging.NullHandler())
