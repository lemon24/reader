"""
reader
======

A minimal feed reader.

Usage
-----

Here is small example of using reader.

Create a Reader object::

    reader = Reader('db.sqlite')

Add a feed::

    reader.add_feed('http://www.hellointernet.fm/podcast?format=rss')

Update all the feeds::

    reader.update_feeds()

Get all the entries, both read and unread::

    entries = list(reader.get_entries())

Mark the first entry as read::

    reader.mark_as_read(entries[0])

Print the titles of the unread entries::

    for e in reader.get_entries(which='unread'):
        print(e.title)


"""

__version__ = '0.1.1'


from .reader import Reader

from .types import Feed, Entry, Content, Enclosure

from .exceptions import (
    ReaderError,
    FeedError, FeedExistsError, FeedNotFoundError, ParseError,
    EntryError, EntryNotFoundError,
    StorageError,
)

