
class ReaderError(Exception):
    """Base for all public exceptions."""


class FeedError(ReaderError):
    """A feed error occured."""

    def __init__(self, url):
        super().__init__(url)

        #: The feed URL.
        self.url = url


class FeedExistsError(FeedError):
    """Feed already exists."""


class FeedNotFoundError(FeedError):
    """Feed not found."""


class ParseError(FeedError):
    """An error occured while getting/parsing feed.

    The original exception should be chained to this one (e.__cause__).

    """


class NotModified(FeedError):
    """Feed not modified."""


class EntryError(ReaderError):
    """An entry error occured."""

    def __init__(self, url, id):
        super().__init__(url, id)

        #: The feed URL.
        self.url = url

        #: The entry id.
        self.id = id

class EntryNotFoundError(EntryError):
    """Entry not found."""


class StorageError(ReaderError):
    """An exception was raised by the underlying storage.

    The original exception should be chained to this one (e.__cause__).

    """

