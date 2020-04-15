class ReaderError(Exception):
    """Base for all public exceptions."""


class FeedError(ReaderError):
    """A feed error occured."""

    def __init__(self, url: str) -> None:
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


class EntryError(ReaderError):
    """An entry error occured."""

    def __init__(self, url: str, id: str) -> None:
        super().__init__(url, id)

        #: The feed URL.
        self.url = url

        #: The entry id.
        self.id = id


class EntryNotFoundError(EntryError):
    """Entry not found."""


class MetadataError(ReaderError):
    """A feed metadata error occured."""

    def __init__(self, url: str, key: str) -> None:
        super().__init__(url, key)

        #: The feed URL.
        self.url = url

        #: The metadata key.
        self.key = key


class MetadataNotFoundError(MetadataError):
    """Feed metadata not found."""


class StorageError(ReaderError):
    """An exception was raised by the underlying storage.

    The original exception should be chained to this one (e.__cause__).

    """


class SearchError(ReaderError):
    """A search-related exception.

    If caused by an exception raised by the underlying search provider,
    the original exception should be chained to this one (e.__cause__).

    """


class SearchNotEnabledError(SearchError):
    """A search-related method was called when search was not enabled."""


class InvalidSearchQueryError(SearchError):
    """The search query provided was somehow invalid."""


class _NotModified(FeedError):
    """Feed not modified.

    Signaling exception used internally by Parser.

    """
