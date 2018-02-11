
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

