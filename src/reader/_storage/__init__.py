from __future__ import annotations

from .._types import SearchType
from ._base import StorageBase
from ._entries import EntriesMixin
from ._feeds import FeedsMixin
from ._tags import TagsMixin


APPLICATION_ID = int(''.join(f'{ord(c):x}' for c in 'read'), 16)

# Row value support was added in 3.15.
# TODO: Remove the Search.update() check once this gets bumped to >=3.18.
MINIMUM_SQLITE_VERSION = (3, 15)
# We use the JSON1 extension for entries.content.
REQUIRED_SQLITE_FUNCTIONS = ['json_array_length']


class Storage(FeedsMixin, EntriesMixin, TagsMixin, StorageBase):
    """Data access object used for all storage (except search).

    This class is split into per-domain mixins, add new methods accordingly.

    Add a test_storage.py::test_errors_locked test for each new public method.

    """

    def make_search(self) -> SearchType:
        from ._search import Search

        return Search(self)
