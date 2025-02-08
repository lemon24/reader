from __future__ import annotations

from collections.abc import Sequence
from functools import cached_property
from typing import Any
from typing import TypeVar


class _FancyExceptionBase(Exception):
    """Exception base that renders a message and __cause__ in str(e).

    The message looks something like:

        [message: ][_str][: CauseType: cause as string]

    The resulting exception pickles successfully;
    __cause__ still gets lost per https://bugs.python.org/issue29466,
    but a string representation of it remains stored on the exception.

    """

    #: Default message; overridable.
    _default_message: str = ''

    def __init__(self, message: str = ''):
        self._message = message or self._default_message

    @property
    def _str(self) -> str:
        """The exception's unique attributes, as string; overridable."""
        return ''

    @property
    def message(self) -> str:
        """The message passed in the constructor, or a default message.

        .. versionchanged:: 3.8
            Became read-only.

        """
        # read-only for compatibility with ExceptionGroup
        return self._message

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
        return ': '.join(filter(None, parts))


class ReaderError(_FancyExceptionBase):
    """Base for all public exceptions."""


class ReaderWarning(ReaderError, UserWarning):
    """Base for all warnings emitted by *reader*
    that are not :exc:`DeprecationWarning`.

    .. versionadded:: 2.13

    .. versionchanged:: 3.8
        Inherit from :exc:`ReaderError`.

    """


class ResourceNotFoundError(ReaderError):
    """Resource (feed, entry) not found.

    .. versionadded:: 2.8

    """

    @property
    def resource_id(self) -> tuple[str, ...]:  # pragma: no cover
        """The `resource_id` of the resource."""
        raise NotImplementedError


class FeedError(ReaderError):
    """A feed error occurred.

    .. versionchanged:: 3.0
        The ``url`` argument is now positional-only.

    """

    def __init__(self, url: str, /, message: str = '') -> None:
        super().__init__(message)

        #: The feed URL.
        self.url = url

    @property
    def _str(self) -> str:
        return repr(self.url)

    @property
    def resource_id(self) -> tuple[str]:
        """Alias for (:attr:`~url`,).

        .. versionadded:: 2.17

        """
        return (self.url,)


class FeedExistsError(FeedError):
    """Feed already exists."""

    _default_message = "feed exists"


class FeedNotFoundError(FeedError, ResourceNotFoundError):
    """Feed not found."""

    _default_message = "no such feed"


class InvalidFeedURLError(FeedError, ValueError):
    """Invalid feed URL.

    .. versionadded:: 2.5

    """

    _default_message = "invalid feed URL"


class EntryError(ReaderError):
    """An entry error occurred.

    .. versionchanged:: 1.18
        The ``url`` argument/attribute was renamed to ``feed_url``.

    .. versionchanged:: 3.0
        The ``feed_url`` and ``id`` arguments are now positional-only.

    """

    def __init__(self, feed_url: str, id: str, /, message: str = '') -> None:
        super().__init__(message)

        #: The feed URL.
        self.feed_url = feed_url

        #: The entry id.
        self.id = id

    @property
    def _str(self) -> str:
        return repr((self.feed_url, self.id))

    @property
    def resource_id(self) -> tuple[str, str]:
        """Alias for (:attr:`~feed_url`, :attr:`~id`).

        .. versionadded:: 2.17

        """
        return self.feed_url, self.id


class EntryExistsError(EntryError):
    """Entry already exists.

    .. versionadded:: 2.5

    """

    _default_message = "entry exists"


class EntryNotFoundError(EntryError, ResourceNotFoundError):
    """Entry not found."""

    _default_message = "no such entry"


class UpdateError(ReaderError):
    """An error occurred while updating the feed.

    Parent of all update-related exceptions.

    .. versionadded:: 3.8

    """


class ParseError(UpdateError, FeedError, ReaderWarning):
    """An error occurred while retrieving/parsing the feed.

    The original exception should be chained to this one (e.__cause__).

    .. versionchanged:: 3.8
        Inherit from :exc:`UpdateError`.

    """


class UpdateHookError(UpdateError):
    r"""One or more update hooks (unexpectedly) failed.

    Not raised directly;
    allows catching any hook errors with a single except clause.

    To inspect individual hook failures,
    use `except\* <exceptstar_>`_ with :exc:`SingleUpdateHookError`
    (or, on Python earlier than 3.11,
    check if the exception :func:`isinstance` :exc:`UpdateHookErrorGroup`
    and examine its :attr:`~BaseExceptionGroup.exceptions`).

    .. _exceptstar: https://docs.python.org/3/tutorial/errors.html#raising-and-handling-multiple-unrelated-exceptions

    .. versionadded:: 3.8

    """


class SingleUpdateHookError(UpdateHookError):
    """An update hook (unexpectedly) failed.

    The original exception should be chained to this one (e.__cause__).

    .. versionadded:: 3.8

    """

    _default_message = "unexpected hook error"

    def __init__(
        self,
        when: str,
        hook: Any,
        resource_id: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__()

        #: The update phase (the hook type). One of:
        #:
        #: * ``'before_feeds_update'``
        #: * ``'before_feed_update'``
        #: * ``'after_entry_update'``
        #: * ``'after_feed_update'``
        #: * ``'after_feeds_update'``
        #:
        self.when = when

        #: The hook.
        self.hook = hook

        #: The `resource_id` of the resource, if any.
        self.resource_id = resource_id

    @property
    def _str(self) -> str:
        parts = [self.when, repr(self.hook)]
        if self.resource_id is not None:
            if len(self.resource_id) == 1:
                parts.append(repr(self.resource_id[0]))
            else:
                parts.append(repr(self.resource_id))
        return ': '.join(parts)


_UpdateHookErrorT = TypeVar('_UpdateHookErrorT', bound=UpdateHookError)


class UpdateHookErrorGroup(ExceptionGroup[_UpdateHookErrorT], UpdateHookError):
    r"""A (possibly nested) :exc:`ExceptionGroup` of :exc:`UpdateHookError`\s.

    .. versionadded:: 3.8

    """

    def __init__(self, msg: str, excs: Sequence[_UpdateHookErrorT], /):
        super().__init__(msg, excs)
        for e in self.exceptions:
            if not isinstance(e, UpdateHookError):
                raise TypeError(
                    "UpdateHookErrorGroup can only contain UpdateHookError; "
                    f"got {type(e).__name__}"
                )

    # https://github.com/python/typeshed/issues/9922
    def derive(  # type: ignore[override]
        self, excs: Sequence[_UpdateHookErrorT], /
    ) -> ExceptionGroup[_UpdateHookErrorT]:
        return UpdateHookErrorGroup(self.message, excs)


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

    _default_message = "operation not supported with search disabled"


class InvalidSearchQueryError(SearchError, ValueError):
    """The search query provided was somehow invalid."""


class PluginError(ReaderError):
    """A plugin-related exception."""


class InvalidPluginError(PluginError, ValueError):
    """An invalid plugin was provided.

    .. versionadded:: 1.16

    """


class PluginInitError(PluginError):
    """A plugin failed to initialize.

    The original exception should be chained to this one (e.__cause__).

    .. versionadded:: 3.0

    """


class TagError(ReaderError):
    """A tag error occurred.

    .. versionadded:: 2.8

    .. versionchanged:: 2.17
        Signature changed from ``TagError(key, object_id, ...)``
        to ``TagError(key, resource_id, ...)``.

    .. versionchanged:: 3.0
        Signature changed from ``TagError(key, resource_id, ...)``
        to ``TagError(resource_id, key, ...)``.

    .. versionchanged:: 3.0
        The ``resource_id`` and ``key`` arguments are now positional-only.

    """

    def __init__(
        self, resource_id: tuple[str, ...], key: str, /, message: str = ''
    ) -> None:
        super().__init__(message)

        #: The `resource_id` of the resource.
        self.resource_id = resource_id

        #: The tag key.
        self.key = key

    @property
    def _str(self) -> str:
        parts = self.resource_id + (self.key,)
        return ': '.join(repr(part) for part in parts)


class TagNotFoundError(TagError):
    """Tag not found.

    .. versionadded:: 2.8

    """

    _default_message = "no such tag"


class ChangeTrackingNotEnabledError(StorageError):
    """A change tracking method was called when change tracking was not enabled.

    .. admonition:: Unstable

        This exception is part of the unstable :ref:`change tracking API <changes>`.

    """

    _default_message = "operation not supported with change tracking disabled"
