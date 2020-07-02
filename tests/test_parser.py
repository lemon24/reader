import io
import logging

import feedparser
import pytest
from utils import make_url_base

from reader import Feed
from reader._parser import Parser
from reader.exceptions import _NotModified
from reader.exceptions import ParseError


@pytest.fixture
def parse():
    parse = Parser()
    yield parse


def _make_relative_path_url(**_):
    return lambda feed_path: feed_path.relto(feed_path.join('../..'))


make_relative_path_url = pytest.fixture(_make_relative_path_url)


def _make_absolute_path_url(**_):
    return lambda feed_path: str(feed_path)


def _make_http_url(requests_mock, **_):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        headers = {}
        if feed_path.ext == '.rss':
            headers['Content-Type'] = 'application/x-rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        requests_mock.get(url, text=feed_path.read(), headers=headers)
        return url

    return make_url


make_http_url = pytest.fixture(_make_http_url)


def _make_https_url(requests_mock, **_):
    def make_url(feed_path):
        url = 'https://example.com/' + feed_path.basename
        headers = {}
        if feed_path.ext == '.rss':
            headers['Content-Type'] = 'application/x-rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        requests_mock.get(url, text=feed_path.read(), headers=headers)
        return url

    return make_url


def _make_http_gzip_url(requests_mock, **_):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        headers = {}
        if feed_path.ext == '.rss':
            headers['Content-Type'] = 'application/x-rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        headers['Content-Encoding'] = 'gzip'

        import io, gzip

        compressed_file = io.BytesIO()
        gz = gzip.GzipFile(fileobj=compressed_file, mode='wb')
        gz.write(feed_path.read_binary())
        gz.close()

        requests_mock.get(url, content=compressed_file.getvalue(), headers=headers)
        return url

    return make_url


def _make_http_url_missing_content_type(requests_mock, **_):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        requests_mock.get(url, text=feed_path.read())
        return url

    return make_url


@pytest.fixture(
    params=[
        _make_relative_path_url,
        _make_absolute_path_url,
        _make_http_url,
        _make_https_url,
        _make_http_gzip_url,
        _make_http_url_missing_content_type,
    ]
)
def make_url(request, requests_mock):
    return request.param(requests_mock=requests_mock)


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
@pytest.mark.parametrize('data_file', ['full', 'empty', 'relative'])
def test_parse(monkeypatch, feed_type, data_file, parse, make_url, data_dir):
    monkeypatch.chdir(data_dir.dirname)

    feed_filename = '{}.{}'.format(data_file, feed_type)
    feed_url = make_url(data_dir.join(feed_filename))

    url_base, rel_base = make_url_base(feed_url)
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(data_dir.join(feed_filename + '.py').read(), expected)

    feed, entries, _, _ = parse(feed_url)
    entries = list(entries)

    assert feed == expected['feed']
    assert entries == expected['entries']


def test_feedparser_exceptions(monkeypatch, parse, data_dir):
    """parse() should reraise most feedparser exceptions."""

    feedparser_exception = Exception("whatever")
    old_feedparser_parse = feedparser.parse

    def feedparser_parse(*args, **kwargs):
        rv = old_feedparser_parse(*args, **kwargs)
        rv['bozo'] = 1
        rv['bozo_exception'] = feedparser_exception
        return rv

    monkeypatch.setattr('feedparser.parse', feedparser_parse)

    with pytest.raises(ParseError) as excinfo:
        parse(str(data_dir.join('full.atom')))

    assert excinfo.value.__cause__ is feedparser_exception


@pytest.mark.parametrize(
    'exc_cls', [feedparser.CharacterEncodingOverride, feedparser.NonXMLContentType]
)
def test_parse_survivable_feedparser_exceptions(
    monkeypatch, caplog, parse, data_dir, exc_cls
):
    """parse() should not reraise some acceptable feedparser exceptions."""

    old_feedparser_parse = feedparser.parse

    def feedparser_parse(*args, **kwargs):
        rv = old_feedparser_parse(*args, **kwargs)
        rv['bozo'] = 1
        rv['bozo_exception'] = exc_cls("whatever")
        return rv

    monkeypatch.setattr('feedparser.parse', feedparser_parse)

    with caplog.at_level(logging.WARNING, logger="reader"):
        # shouldn't raise an exception
        parse(str(data_dir.join('full.atom')))

    warnings = [
        message
        for logger, level, message in caplog.record_tuples
        if logger == 'reader' and level == logging.WARNING
    ]
    assert sum('full.atom' in m and exc_cls.__name__ in m for m in warnings) > 0


@pytest.fixture
def make_http_url_304(requests_mock):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        requests_mock.get(url, status_code=304)
        return url

    yield make_url


def test_parse_not_modified(monkeypatch, parse, make_http_url_304, data_dir):
    """parse() should raise _NotModified for unchanged feeds."""

    feed_url = make_http_url_304(data_dir.join('full.atom'))

    with pytest.raises(_NotModified):
        parse(feed_url)


@pytest.fixture
def make_http_get_headers_url(requests_mock):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        headers = {}
        if feed_path.ext == '.rss':
            headers['Content-Type'] = 'application/x-rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'

        def callback(request, context):
            make_url.request_headers = request.headers
            return feed_path.read()

        requests_mock.get(url, text=callback, headers=headers)
        return url

    yield make_url


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_parse_sends_etag_last_modified(
    parse, make_http_get_headers_url, data_dir, feed_type,
):
    feed_url = make_http_get_headers_url(data_dir.join('full.' + feed_type))
    parse(feed_url, 'etag', 'last_modified')

    headers = make_http_get_headers_url.request_headers

    assert headers.get('If-None-Match') == 'etag'
    assert headers.get('If-Modified-Since') == 'last_modified'


@pytest.fixture
def make_http_etag_last_modified_url(requests_mock):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        headers = {'ETag': make_url.etag, 'Last-Modified': make_url.last_modified}
        if feed_path.ext == '.rss':
            headers['Content-Type'] = 'application/x-rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        requests_mock.get(url, text=feed_path.read(), headers=headers)
        return url

    yield make_url


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_parse_returns_etag_last_modified(
    monkeypatch,
    parse,
    make_http_etag_last_modified_url,
    make_http_url,
    make_relative_path_url,
    data_dir,
    feed_type,
):
    monkeypatch.chdir(data_dir.dirname)

    make_http_etag_last_modified_url.etag = 'etag'
    make_http_etag_last_modified_url.last_modified = 'last_modified'

    feed_url = make_http_etag_last_modified_url(data_dir.join('full.' + feed_type))
    _, _, etag, last_modified = parse(feed_url)

    assert etag == 'etag'
    assert last_modified == 'last_modified'

    feed_url = make_http_url(data_dir.join('full.atom'))
    _, _, etag, last_modified = parse(feed_url)

    assert etag == last_modified == None

    feed_url = make_relative_path_url(data_dir.join('full.' + feed_type))
    _, _, etag, last_modified = parse(feed_url)

    assert etag == last_modified == None


@pytest.mark.parametrize('tz', ['UTC', 'Europe/Helsinki'])
def test_parse_local_timezone(monkeypatch, request, parse, tz, data_dir):
    """parse() return the correct dates regardless of the local timezone."""

    feed_path = data_dir.join('full.atom')

    url_base, rel_base = make_url_base(str(feed_path))
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(feed_path.new(ext='.atom.py').read(), expected)

    import time

    request.addfinalizer(time.tzset)
    monkeypatch.setenv('TZ', tz)
    time.tzset()
    feed, _, _, _ = parse(str(feed_path))
    assert feed.updated == expected['feed'].updated


def test_parse_response_plugins(monkeypatch, tmpdir, make_http_url, data_dir):
    feed_url = make_http_url(data_dir.join('empty.atom'))
    make_http_url(data_dir.join('full.atom'))

    import requests

    def do_nothing_plugin(session, response, request):
        do_nothing_plugin.called = True
        assert isinstance(session, requests.Session)
        assert isinstance(response, requests.Response)
        assert isinstance(request, requests.Request)
        assert request.url == feed_url
        return None

    def rewrite_to_empty_plugin(session, response, request):
        rewrite_to_empty_plugin.called = True
        request.url = request.url.replace('empty', 'full')
        return request

    parse = Parser()
    parse.response_plugins.append(do_nothing_plugin)
    parse.response_plugins.append(rewrite_to_empty_plugin)

    feed, _, _, _ = parse(feed_url)
    assert do_nothing_plugin.called
    assert rewrite_to_empty_plugin.called
    assert feed.link is not None


def test_parse_requests_exception(monkeypatch, parse):
    exc = Exception('exc')

    def raise_exc():
        raise exc

    import requests

    monkeypatch.setattr(requests, 'Session', raise_exc)

    with pytest.raises(ParseError) as excinfo:
        parse('http://example.com')

    assert excinfo.value.__cause__ is exc


def test_user_agent(parse, make_http_get_headers_url, data_dir):
    feed_url = make_http_get_headers_url(data_dir.join('full.atom'))
    parse(feed_url)

    headers = make_http_get_headers_url.request_headers
    assert headers['User-Agent'].startswith('python-reader/')


def test_user_agent_none(parse, make_http_get_headers_url, data_dir):
    feed_url = make_http_get_headers_url(data_dir.join('full.atom'))
    parse.user_agent = None
    parse(feed_url)

    headers = make_http_get_headers_url.request_headers
    assert 'reader' not in headers['User-Agent']


def test_make_feedparser_parse(monkeypatch, parse, data_dir):
    # TODO: Remove this once we start using feedparser 6.0.

    exc = Exception("whatever")

    def feedparser_parse(
        *args, resolve_relative_uris=None, sanitize_html=None,
    ):
        feedparser_parse.kwargs = resolve_relative_uris, sanitize_html
        raise exc

    monkeypatch.setattr('feedparser.parse', feedparser_parse)

    with pytest.raises(Exception) as excinfo:
        parse(str(data_dir.join('full.atom')))
    assert excinfo.value is exc

    assert feedparser_parse.kwargs == (True, True)


def test_missing_entry_id(parse):
    """Handle RSS entries without guid.
    https://github.com/lemon24/reader/issues/170

    """
    # TODO: this test is brittle, Parser accepting feed text is unintended
    # and may be removed after https://github.com/lemon24/reader/issues/155

    # For RSS, when id is missing, parse() falls back to link.
    result = parse(
        """
        <?xml version="1.0" encoding="UTF-8" ?>
        <rss version="2.0">
        <channel>
            <item>
                <link>http://www.example.com/blog/post/1</link>
                <title>Example entry</title>
                <description>Here is some text.</description>
                <pubDate>Sun, 06 Sep 2009 16:20:00 +0000</pubDate>
            </item>
        </channel>
        </rss>
        """.strip()
    )
    (entry,) = list(result.entries)
    assert entry.id == entry.link

    # ... and only link.
    with pytest.raises(ParseError):
        parse(
            """
            <?xml version="1.0" encoding="UTF-8" ?>
            <rss version="2.0">
            <channel>
                <item>
                    <title>Example entry</title>
                    <description>Here is some text.</description>
                    <pubDate>Sun, 06 Sep 2009 16:20:00 +0000</pubDate>
                </item>
            </channel>
            </rss>
            """.strip()
        )

    # There is no fallback for Atom.
    with pytest.raises(ParseError):
        parse(
            """
            <?xml version="1.0" encoding="utf-8"?>
            <feed xmlns="http://www.w3.org/2005/Atom">
                <entry>
                    <title>Atom-Powered Robots Run Amok</title>
                    <link href="http://example.org/2003/12/13/atom03"/>
                    <updated>2003-12-13T18:30:02Z</updated>
                    <summary>Some text.</summary>
                </entry>
            </feed>
            """.strip()
        )


def test_no_version(parse):
    """Raise ParseError if feedparser can't detect the feed type and
    there's no bozo_exception.

    """
    with pytest.raises(ParseError):
        parse(
            """
            <?xml version="1.0" encoding="utf-8"?>
            <element>aaa</element>
            """.strip()
        )
