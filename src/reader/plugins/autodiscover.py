"""
.autodiscover
~~~~~~~~~~~~~

If feed parsing fails, try to discover feed links in the response,
and store them in the feed's ``.reader.autodiscover`` tag
(for an application to then suggest to the user).

The tag value is a list of link dicts
with the same fields as :class:`reader.discover.Link`::

    >>> reader.get_tag(feed, '.reader.autodiscover')
    [{'href': 'http://example.com/rss', 'title': 'Example', 'type': 'application/rss+xml'}]


.. versionadded:: 3.25

..
    Implemented for https://github.com/lemon24/reader/issues/404
    Better version of https://github.com/lemon24/reader/issues/150

"""

import json
from dataclasses import asdict
from functools import wraps

from reader import ParseError
from reader._parser import HTTPInfo
from reader.discover import from_http_response

TAG = 'autodiscover'
HEADER = f'x-reader-{TAG}'


def init_reader(reader):
    # setting parser.parse early triggers the non-lazy imports :(
    if hasattr(reader._parser, '_post_init'):  # pragma: no cover
        reader._parser._post_init.append(patch_parse)
    else:  # pragma: no cover
        patch_parse(reader._parser)
    reader.after_feed_update_hooks.append(save_links_as_tag)


def patch_parse(parser):
    parse = parser.parse

    @wraps(parse)
    def wrapper(url, retrieved):
        try:
            return parse(url, retrieved)
        except ParseError:
            extract_feeds_to_http_headers(url, retrieved)
            raise

    parser.parse = wrapper


def extract_feeds_to_http_headers(url, retrieved):
    file = reset_file(retrieved.resource)
    if not file:
        return

    headers = retrieved.http_info.headers if retrieved.http_info else {}
    links = from_http_response(url, file, headers)
    if not links:
        return

    if not retrieved.http_info:
        object.__setattr__(retrieved, 'http_info', HTTPInfo(200, {}))

    retrieved.http_info.headers[HEADER] = json.dumps(list(map(asdict, links)))


def reset_file(file):
    if not (hasattr(file, 'seek') and hasattr(file, 'read')):
        return None
    try:
        file.seek(0)
    except OSError:  # pragma: no cover
        return None
    return file


def save_links_as_tag(reader, feed, http_info):
    links = []
    if http_info:
        if links_str := http_info.headers.get(HEADER):
            links = json.loads(links_str)

    key = reader.make_reader_reserved_name(TAG)
    if links:
        reader.set_tag(feed, key, links)
    else:
        reader.delete_tag(feed, key, missing_ok=True)
