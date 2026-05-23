import io

import pytest

from reader.discover import from_html
from reader.discover import from_http_response
from reader.discover import Link

HTML = """
<link rel="stylesheet" href="style.css">
<link rel="alternate" type="application/rss+xml" title="R.SS" href="/r/ss" />
<link rel="alternate" type="application/atom+xml" title="A.tom" href="a/tom" />
<link rel="alternate" type="application/feed+json" href="http://external/j/son" />

<a href="/">home</a>
<a href="/index.xml">XML</a>
<a href="http://external/feed.xml" title="one">two</a>

"""


def test_from_http_response():
    base = 'http://base/path/'

    assert from_http_response(base, HTML, {}) == [
        Link(href='http://base/r/ss', type='application/rss+xml', title='R.SS'),
        Link(href='http://base/path/a/tom', type='application/atom+xml', title='A.tom'),
        Link(href='http://external/j/son', type='application/feed+json'),
    ]

    assert from_http_response(base, HTML.replace('alternate', 'foo'), {}) == [
        Link(href='http://base/index.xml', type=None, title='XML'),
        Link(href='http://external/feed.xml', type=None, title='two'),
    ]

    assert (
        from_http_response(base, HTML, {'content-location': 'http://another'})[0].href
        == 'http://another/r/ss'
    )

    assert from_http_response(base, '', {}) == []
    assert from_http_response(base, HTML, {'content-type': 'image/png'}) == []

    assert from_http_response(
        base,
        io.BytesIO('<a href="/index.xml">£</a>'.encode()),
        {'content-type': 'text/html; charset=cp1252'},
    ) == [Link(href='http://base/index.xml', type=None, title='Â£')]
