"""
Low level support for discovering feeds in HTML pages.

.. autofunction:: from_http_response
.. autofunction:: from_html
.. autoclass:: Link
    :members:

.. versionadded:: 3.25

"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

from ._parser import Headers
from ._parser._http_utils import parse_options_header
from ._storage._html_utils import AnyMarkup
from ._storage._html_utils import get_soup


@dataclass(frozen=True, kw_only=True)
class Link:
    """Data type representing a link."""

    # TODO: unify with Enclosure and https://github.com/lemon24/reader/issues/320 links

    #: The link URL.
    href: str

    #: The link content type.
    type: str | None = None

    #: The link title.
    title: str | None = None


HTML_MIME_TYPES = {'text/html', 'application/xhtml+xml'}


def from_http_response(url: str, content: AnyMarkup, headers: Headers) -> list[Link]:
    """Discover feed links in an HTTP response.

    Args:
        url (str): Request URL.
        content (str or bytes or file): Response content.
        headers (dict(str, str)): Resonse headers.

    Returns:
        list(Link): A list of links.

    """
    # YAGNI: there's also rel=alternate links in the Link header,
    # but in practice they're not present often, and when they are,
    # there's usually a matching <link> tag in the HTML content

    mime_type = None
    encoding = None
    if content_type := headers.get('content-type'):
        mime_type, options = parse_options_header(content_type)
        encoding = options.get('charset')

    if mime_type and mime_type.lower() not in HTML_MIME_TYPES:
        return []

    alternates = list(from_html(content, encoding))

    location = headers.get('content-location')
    if location:
        url = urljoin(url, location)
    for alt in alternates:
        object.__setattr__(alt, 'href', urljoin(url, alt.href))

    # make them unique, keep the first one
    by_href = {alt.href: alt for alt in reversed(alternates)}
    alternates = list(reversed(by_href.values()))

    return alternates


TIER_ONE_SELECTOR = """\
[rel=alternate][href][type="application/rss+xml"],
[rel=alternate][href][type="application/rss"],
[rel=alternate][href][type="application/atom+xml"],
[rel=alternate][href][type="application/atom"],
[rel=alternate][href][type="application/feed+json"],
[rel=alternate][href][type="application/json"][href$="/feed.json"]
"""

TIER_TWO_SELECTOR = """\
a[href$="atom.xml"],
a[href$="/atom"],
a[href$="/atom/"],
a[href$="=atom"],
a[href$="rss.xml"],
a[href$="/rss"],
a[href$="/rss/"],
a[href$="=rss"],
a[href$="index.xml"],
a[href$="/feed.xml"],
a[href$="/feed.json"],
a[href$="/feed"],
a[href$="/feed/"]
"""

SELECTORS = [TIER_ONE_SELECTOR, TIER_TWO_SELECTOR]


def from_html(content: AnyMarkup, encoding: str | None = None) -> list[Link]:
    """Discover feed links in an HTML page.

    Args:
        content (str or bytes or file): HTML content.
        encoding (str or None): Content encoding, if content is bytes.

    Returns:
        list(Link): A list of links.

    """
    # per https://github.com/lemon24/reader/issues/404#issuecomment-4492060583

    soup = get_soup(content, from_encoding=encoding)

    elements = []
    for selector in SELECTORS:
        if elements := list(soup.select(selector)):
            break

    rv = []
    for element in elements:
        attrs = element.attrs
        text = ' '.join(element.stripped_strings)
        rv.append(
            Link(
                href=attrs['href'],
                type=attrs.get('type'),
                title=text or attrs.get('title'),
            )
        )

    return rv
