from __future__ import annotations

from typing import Any

from .._types import SearchType
from ._base import StorageBase
from ._changes import Changes
from ._entries import EntriesMixin
from ._feeds import FeedsMixin
from ._tags import TagsMixin


# Row value support was added in 3.15.
# last_insert_rowid() support for FTS5 was added in 3.18.
MINIMUM_SQLITE_VERSION = (3, 18)

# Both storage and search use the JSON1 extension.
REQUIRED_SQLITE_FUNCTIONS = ['json']


class Storage(FeedsMixin, EntriesMixin, TagsMixin, StorageBase):
    """Data access object used for all storage (except search).

    This class is split into per-domain mixins, add new methods accordingly.

    Add a test_storage.py::test_errors_locked test for each new public method.

    """

    def __init__(self, *args: Any, **kwargs: Any):
        # FIXME: types
        # FIXME: protocol
        super().__init__(*args, **kwargs)
        self.changes = Changes(self)

    def make_search(self) -> SearchType:
        from ._search import Search

        return Search(self)
