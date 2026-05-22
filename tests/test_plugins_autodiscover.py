import io
from contextlib import contextmanager

import pytest

from reader import ParseError
from reader._parser import RetrievedFeed

HTML = '<link rel="alternate" type="application/rss+xml" href="/rss" />'


def test_http(make_reader, requests_mock):
    feed = 'http://example.com/'

    reader = make_reader(':memory:', plugins=['.autodiscover'])
    reader.add_feed(feed)

    headers = {'content-location': 'http://ext.com/'}
    requests_mock.get(feed, status_code=200, text=HTML, headers=headers)

    with pytest.raises(ParseError, match="unknown feed type"):
        reader.update_feed(feed)

    assert reader.get_tag(feed, '.reader.autodiscover', None) == [
        {'href': 'http://ext.com/rss', 'title': None, 'type': 'application/rss+xml'}
    ]

    # check .reader.autodiscover is cleared

    requests_mock.get(feed, status_code=200)

    with pytest.raises(ParseError):
        reader.update_feed(feed)

    assert reader.get_tag(feed, '.reader.autodiscover', None) is None


def test_file(make_reader, tmp_path):
    feed = 'file'

    reader = make_reader(':memory:', plugins=['.autodiscover'], feed_root=tmp_path)
    reader.add_feed(feed)

    (tmp_path / feed).write_text(HTML)

    with pytest.raises(ParseError, match="unknown feed type"):
        reader.update_feed(feed)

    assert reader.get_tag(feed, '.reader.autodiscover', None) == [
        {'href': '/rss', 'title': None, 'type': 'application/rss+xml'}
    ]


def test_resource_is_not_a_file(make_reader):
    feed = 'http://example.com/'

    reader = make_reader(':memory:', plugins=['.autodiscover'])
    reader.add_feed(feed)

    @contextmanager
    def retrieve(*_):
        yield RetrievedFeed('<link />', 'type/subtype')

    reader._parser.retrieve = retrieve

    with pytest.raises(ParseError, match="unknown feed type"):
        reader.update_feed(feed)

    assert reader.get_tag(feed, '.reader.autodiscover', None) == None
