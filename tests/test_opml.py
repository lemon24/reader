import io

import pytest

from reader.opml import OPMLError
from reader.opml import parse
from reader.opml import unparse
from utils import utc_datetime as datetime

OPML_INPUT = b"""\
<?xml version='1.0' encoding='utf8'?>
<opml version="2.0">
  <body>
    <outline
      type="rss"
      title="title"
      text="text"
      xmlUrl="top-level"
      htmlUrl="link"
      description="a feed"
    />
    <Outline
      Type="RSS"
      Text="Text"
      XMLURL="weird-casing"
      htmlurl="link"
    />
    <outline
      type="rss"
      title="Title"
      htmlUrl="missing-xmlurl"
    />
    <outline text="parent">
      <outline type="rss" xmlUrl="nested" />
    </outline>
  </body>
</opml>
"""


OPML_OUTPUT = b"""\
<?xml version='1.0' encoding='utf-8'?>
<opml version="2.0">
  <head>
    <title>my feeds</title>
    <dateCreated>Fri, 01 Jan 2010 00:00:00 +0000</dateCreated>
  </head>
  <body>
    <outline type="rss" title="title" text="title" xmlUrl="top-level" htmlUrl="link" description="a feed" />
    <outline type="rss" title="Text" text="Text" xmlUrl="weird-casing" htmlUrl="link" />
    <outline type="rss" xmlUrl="nested" />
  </body>
</opml>
"""


def test_roundtrip():
    feeds = parse(io.BytesIO(OPML_INPUT))
    output = unparse(feeds, title='my feeds', created=datetime(2010, 1, 1))
    assert output == OPML_OUTPUT


OPML_EMPTY = b"""\
<?xml version='1.0' encoding='utf-8'?>
<opml version="2.0">
  <head />
  <body />
</opml>
"""


def test_empty():
    assert parse(io.BytesIO(OPML_EMPTY)) == []
    assert unparse([]) == OPML_EMPTY


@pytest.mark.parametrize(
    'input, message',
    [
        ('', "XML error"),
        ("<?xml version='1.0' encoding='xyz'?>", "XML error: unknown encoding"),
        ("<outline></outline>", 'expected <opml>'),
        ("<opml><a><b><c></c></b></a></opml>", 'tag depth limit'),
    ],
)
def test_parse_error(input, message):
    with pytest.raises(OPMLError, match=message):
        parse(io.BytesIO(input.encode()), max_depth=3)
