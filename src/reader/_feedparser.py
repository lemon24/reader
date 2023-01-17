from __future__ import annotations

from typing import IO
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ._parser import FeedAndEntries
    from ._requests_utils import Headers


class FeedparserParser:

    # Everything in feedparser.http.ACCEPT_HEADER *except* the wildcard,
    # which gets added back explicitly later on.
    #
    # Not generating this programmatically to allow for lazy imports.
    #
    http_accept = (
        'application/atom+xml,application/rdf+xml,application/rss+xml,'
        'application/x-netcdf,application/xml;q=0.9,text/xml;q=0.2'
    )

    def __call__(
        self,
        url: str,
        resource: IO[bytes],
        headers: Headers | None = None,
    ) -> FeedAndEntries:
        """Like feedparser.parse(), but return a feed and entries,
        and re-raise bozo_exception as ParseError.

        url is NOT passed to feedparser; resource and headers are.

        """

        # lazy import (https://github.com/lemon24/reader/issues/297)
        from ._feedparser_lazy import feedparser, _process_feed

        # feedparser content sanitization and relative link resolution should be ON.
        # https://github.com/lemon24/reader/issues/125
        # https://github.com/lemon24/reader/issues/157
        result = feedparser.parse(  # type: ignore[attr-defined]
            resource,
            resolve_relative_uris=True,
            sanitize_html=True,
            response_headers=headers,
        )
        return _process_feed(url, result)
