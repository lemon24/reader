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

from dataclasses import asdict
from functools import wraps

from reader import ParseError
from reader._parser import RetrieveMetadata
from reader.discover import from_http_response

TAG = 'autodiscover'


def init_reader(reader):
    reader._parser.lazy_init(patch_parse)
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

    links = from_http_response(url, file, retrieved.headers)
    if not links:
        return

    if not retrieved.metadata:
        object.__setattr__(retrieved, 'metadata', RetrieveMetadata())

    retrieved.metadata.extra[TAG] = links


def reset_file(file):
    if not (hasattr(file, 'seek') and hasattr(file, 'read')):
        return None
    try:
        file.seek(0)
    except OSError:  # pragma: no cover
        return None
    return file


def save_links_as_tag(reader, feed, metadata):
    links = []
    if metadata:
        if links := metadata.extra.get(TAG):
            links_json = list(map(asdict, links))

    key = reader.make_reader_reserved_name(TAG)
    if links:
        reader.set_tag(feed, key, links_json)
    else:
        reader.delete_tag(feed, key, missing_ok=True)
