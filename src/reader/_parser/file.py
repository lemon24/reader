from __future__ import annotations

import pathlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from typing import IO

from ..exceptions import ParseError
from . import wrap_exceptions
from ._url_utils import extract_path
from ._url_utils import resolve_root


@dataclass(frozen=True)
class FileRetriever:
    """Bare path and file:// URI parser.

    Allows restricting file-system access to a single directory;
    see :func:`~reader.make_reader` for details.

    """

    feed_root: str

    def __post_init__(self) -> None:
        # give feed_root checks a chance to fail early
        self._normalize_url('known-good-feed-url')

    @contextmanager
    def __call__(self, url: str, *args: Any, **kwargs: Any) -> Iterator[IO[bytes]]:
        try:
            normalized_url = self._normalize_url(url)
        except ValueError as e:
            raise ParseError(url, message=str(e)) from None

        with wrap_exceptions(url, "while reading feed"):
            with open(normalized_url, 'rb') as file:
                yield file

    def validate_url(self, url: str) -> None:
        self._normalize_url(url)

    def _normalize_url(self, url: str) -> str:
        path = extract_path(url)
        if self.feed_root:
            path = resolve_root(self.feed_root, path)
            if pathlib.PurePath(path).is_reserved():
                raise ValueError("path must not be reserved")
        return path
