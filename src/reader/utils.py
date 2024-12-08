"""Too specific to be in core, too small to have dedicated modules."""

from collections.abc import Collection
from urllib.parse import urlencode

from . import EntryExistsError
from . import FeedExistsError
from . import Reader
from .types import _entry_argument
from .types import EntryInput


def archive_entries(
    reader: Reader,
    entries: Collection[EntryInput],
    /,
    feed_url: str = 'reader:archived',
    feed_user_title: str | None = 'Archived',
) -> None:
    """Copy a list of entries to a special "archived" feed.

    Entries that are already in the archived feed will be overwritten.

    The original entries will remain unchanged.

    Args:
        reader (Reader): A reader instance.
        entries (list(tuple(str, str) or Entry)): Entries to be archived.
        feed_url (str):
            The URL of the archived feed.
            If the feed does not exist, it will be created.
        feed_user_title (str or None):
            :attr:`~.Feed.user_title` for the archived feed.

    Raises:
        EntryExistsError: If any of the entries does not exist.
        StorageError

    .. versionadded:: 3.16

    """
    entry_ids = [_entry_argument(e) for e in entries]

    try:
        reader.add_feed(feed_url, allow_invalid_url=True)
        reader.disable_feed_updates(feed_url)
    except FeedExistsError:
        pass
    reader.set_feed_user_title(feed_url, feed_user_title)

    for src in entry_ids:
        dst = feed_url, _make_archived_entry_id(feed_url, src)
        try:
            reader.copy_entry(src, dst)
        except EntryExistsError:
            reader.delete_entry(dst)
            reader.copy_entry(src, dst)

    # TODO: ideally, archiving may redirect to a view of the archived entries
    #
    # this can be achieved in one of the following ways:
    #
    # * filter by the archived entry ids
    #   * get_entries(entries=...) does not exist
    #   * if there are a lot of entries, the query string may be to big
    # * filter by entry source – get_entries(source=...)
    #   * this will not include entries that already have a source
    #   * idem for original_feed_url
    # * filter by entry id prefix – reader:archived?feed=...&
    #   * get_entries(entry_id_prefix=...) does not exist
    #   * by far the most correct
    #
    # until we figure this out, leaving return type to None


def _make_archived_entry_id(feed_url: str, entry: tuple[str, str]) -> str:
    query = urlencode({'feed': entry[0], 'entry': entry[1]})
    return f"{feed_url}?{query}"
