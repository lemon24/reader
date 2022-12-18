from reader._feedparser import FeedparserParser
from reader._feedparser_lazy import feedparser
from reader._http_utils import parse_accept_header
from reader._http_utils import unparse_accept_header


def test_feedparserparser_http_accept_up_to_date():
    assert FeedparserParser.http_accept == unparse_accept_header(
        t for t in parse_accept_header(feedparser.http.ACCEPT_HEADER) if '*' not in t[0]
    )
