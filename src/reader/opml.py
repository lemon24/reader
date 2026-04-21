import io
import re
import xml.etree.ElementTree as etree
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import KW_ONLY
from datetime import datetime
from email.utils import format_datetime
from typing import cast
from typing import IO

import reader

# Implementation note:
# We're not using listparser because of the extra dependency
# and its weird category handling (should we add categories),
# and because we still have to implement unparse() anyway.


@dataclass
class Feed:
    """A feed in an OPML subscription list."""

    # the similarity to reader.Feed is deliberate
    url: str
    _: KW_ONLY
    title: str | None = None
    link: str | None = None
    subtitle: str | None = None


class OPMLError(reader.ReaderError):
    pass


def parse(file: IO[bytes], max_depth: int = 10) -> list[Feed]:
    """Extract a list of feeds from an OPML subscription list.

    Raises:
        OPMLError:

    """
    file = _fix_xml_decl_encoding(file)
    try:
        tree = etree.parse(file)
    except (etree.ParseError, LookupError) as e:
        raise OPMLError(f"XML error: {e}") from e

    root = tree.getroot()
    if root.tag.lower() != 'opml':
        raise OPMLError(f"expected <opml> root tag, got: <{root.tag}>")

    def walk(node: etree.Element, depth: int = 1) -> Iterable[Feed]:
        if depth > max_depth:
            raise OPMLError("tag depth limit exceeded")

        # case-insensitive for robustness
        tag = node.tag.lower()
        attrib = {k.lower(): v for k, v in node.attrib.items()}
        # case-insensitive per spec
        type = attrib.get('type', '').lower()

        if tag == 'outline' and type == 'rss':
            if url := attrib.get('xmlurl'):
                yield Feed(
                    url,
                    title=attrib.get('title', attrib.get('text')),
                    link=attrib.get('htmlurl'),
                    subtitle=attrib.get('description'),
                )

        for child in node:
            yield from walk(child, depth + 1)

    return list(walk(root))


XML_DECL_RE = rb"""(?xi)
    ^(
        [\xfe\xff\s]*
        <\?xml .*?
        \s encoding \s* = \s* ['"] utf )( \d+ ['"]
        .*? \?>
    )
"""
XML_DECL_REPL = rb"\1-\2"


def _fix_xml_decl_encoding(file: IO[bytes]) -> IO[bytes]:
    """Fix misspelled utf8 encoding in XML declaration (breaks etree).

    Work-around for https://github.com/python/cpython/issues/148821

    """
    line = next(file, None)
    if not line:
        return file

    line = re.sub(XML_DECL_RE, XML_DECL_REPL, line, count=1)

    new_file = io.BytesIO()
    new_file.write(line)
    new_file.write(file.read())
    new_file.seek(0)

    return new_file


def unparse(
    feeds: Iterable[reader.Feed],
    *,
    title: str | None = None,
    created: datetime | None = None,
) -> bytes:
    """Convert a list of feeds to an OPML subscription list."""
    opml = _add_element(None, 'opml', version='2.0')
    head = _add_element(opml, 'head')
    if title:
        _add_element(head, 'title', title)
    if created:
        _add_element(head, 'dateCreated', format_datetime(created))

    body = _add_element(opml, 'body')
    for feed in feeds:
        _add_element(
            body,
            'outline',
            type='rss',
            title=feed.title,
            text=feed.title,
            xmlUrl=feed.url,
            htmlUrl=feed.link,
            description=feed.subtitle,
        )

    etree.indent(opml)
    rv = cast(bytes, etree.tostring(opml, encoding="utf-8", xml_declaration=True))
    return rv + b'\n'


def _add_element(
    _parent: etree.Element | None,
    _tag: str,
    _text: str | None = None,
    **kwargs: str | None,
) -> etree.Element:
    attrib = {k: v for k, v in kwargs.items() if v is not None}
    element = etree.Element(_tag, attrib)
    element.text = _text
    if _parent is not None:
        _parent.append(element)
    return element
