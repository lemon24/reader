import warnings
from typing import Any
from typing import Tuple

from ._vendor.functools import cached_property


class _FancyExceptionBase(Exception):

    """Exception base that renders a message and __cause__ in str(e).

    The message looks something like:

        [message: ][_str][: CauseType: cause as string]

    The resulting exception pickles successfully;
    __cause__ still gets lost per https://bugs.python.org/issue29466,
    but a string representation of it remains stored on the exception.

    """

    #: Message; overridable.
    message: str = ''

    @property
    def _str(self) -> str:
        """The exception's unique attributes, as string; overridable."""
        return ''

    def __init__(self, message: str = ''):
        if message:
            self.message = message

    @cached_property
    def _cause_name(self) -> str:
        if not self.__cause__:
            return ''
        t = type(self.__cause__)
        return f'{t.__module__}.{t.__qualname__}'

    @cached_property
    def _cause_str(self) -> str:
        return str(self.__cause__) if self.__cause__ else ''

    def __reduce__(self) -> object:  # type: ignore
        # "prime" the cached properties before pickling
        str(self)
        return super().__reduce__()

    def __str__(self) -> str:
        parts = [self.message, self._str, self._cause_name, self._cause_str]
        # map is here to only to please mypy on python <3.8
        return ': '.join(map(str, filter(None, parts)))


class ReaderError(_FancyExceptionBase):
    """Base for all public exceptions."""


class FeedError(ReaderError):
    """A feed error occured."""

    def __init__(self, url: str, message: str = '') -> None:
        super().__init__(message)

        #: The feed URL.
        self.url = url

    @property
    def _str(self) -> str:
        return repr(self.url)

    @property
    def object_id(self) -> str:
        """Alias for :attr:`~FeedError.url`.

        .. versionadded:: 1.12

        """
        return self.url


class FeedExistsError(FeedError):
    """Feed already exists."""

    message = "feed exists"


class FeedNotFoundError(FeedError):
    """Feed not found."""

    message = "no such feed"


class ParseError(FeedError):
    """An error occured while getting/parsing feed.

    The original exception should be chained to this one (e.__cause__).

    """


class EntryError(ReaderError):
    """An entry error occurred.

    .. versionchanged:: 1.18
        The ``url`` argument/attribute was renamed to ``feed_url``.
    """

    def __init__(self, feed_url: str, id: str, message: str = '') -> None:
        super().__init__(message)

        #: The feed URL.
        self.feed_url = feed_url

        #: The entry id.
        self.id = id

    @property
    def _str(self) -> str:
        return repr((self.feed_url, self.id))

    @property
    def object_id(self) -> Tuple[str, str]:
        """Alias for (:attr:`~EntryError.url`, :attr:`~EntryError.id`).

        .. versionadded:: 1.12

        """
        return self.feed_url, self.id

    @property
    def url(self) -> str:
        """Deprecated alias for :attr:`EntryError.feed_url`.

        .. deprecated: 1.18

        """
        warnings.warn(
            "EntryError.url is deprecated "
            "and will be removed in reader 2.0. "
            "Use EntryError.feed_url instead.",
            DeprecationWarning,
        )
        return self.feed_url


class EntryNotFoundError(EntryError):
    """Entry not found."""

    message = "no such entry"


class MetadataError(ReaderError):
    """A metadata error occurred.

    .. versionchanged:: 1.18

        Signature changed from ``MetadataError(message='')``
        to ``MetadataError(key, message='')``.

    """

    def __init__(self, *args: Any, key: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        #: The metadata key.
        self.key = key

    @property
    def _str(self) -> str:
        return f"{super()._str}: {self.key!r}"


class MetadataNotFoundError(MetadataError):
    """Metadata not found.

    .. versionchanged:: 1.18

        Signature changed from ``MetadataNotFoundError(url, key, message='')``
        to ``MetadataNotFoundError(key, message='')``.

    """

    message = "no such metadata"


class FeedMetadataNotFoundError(MetadataNotFoundError, FeedError):
    """Feed metadata not found.

    .. versionadded:: 1.18

    """

    def __init__(self, url: str, key: str, message: str = '') -> None:
        super().__init__(url, key=key, message=message)


class EntryMetadataNotFoundError(MetadataNotFoundError, EntryError):
    """Entry metadata not found.

    .. versionadded:: 1.18

    """

    def __init__(self, feed_url: str, id: str, key: str, message: str = '') -> None:
        super().__init__(feed_url, id, key=key, message=message)


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

    message = "operation not supported with search disabled"


class InvalidSearchQueryError(SearchError, ValueError):
    """The search query provided was somehow invalid."""


class PluginError(ReaderError):
    """A plugin-related exception."""


class InvalidPluginError(PluginError, ValueError):
    """An invalid plugin was provided."""
