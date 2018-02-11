
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

    def __init__(self, *args, **kwargs):
        self.exception = kwargs.pop('exception', None)
        super().__init__(*args, **kwargs)


class NotModified(FeedError):
    """Feed not modified."""

