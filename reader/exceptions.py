
class ReaderError(Exception):
    """Base for all public exceptions."""


class FeedError(ReaderError):
    """A feed error occured."""

    def __init__(self, url):
        super().__init__(url)
        self.url = url


class FeedExistsError(FeedError):
    """File already exists."""


class FeedNotFoundError(FeedError):
    """Feed not found."""


class ParseError(FeedError):
    """An error occured while getting/parsing feed."""


class NotModified(FeedError):
    """Feed not modified."""


class EntryError(ReaderError):
    """An entry error occured."""

    def __init__(self, url, id):
        super().__init__(url, id)
        self.url = url
        self.id = id

class EntryNotFoundError(EntryError):
    """Entry not found."""

