import io
import json
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
import requests

from reader import Feed
from reader._parser import default_parser
from reader._parser import FeedForUpdate
from reader._parser import HTTPInfo
from reader._parser import Parser
from reader._parser import RetrievedFeed
from reader._parser import RetrieveError
from reader._parser.feedparser import feedparser
from reader._parser.feedparser import FeedparserParser
from reader._parser.file import FileRetriever
from reader._parser.jsonfeed import JSONFeedParser
from reader._parser.requests import SessionWrapper
from reader._types import FeedData
from reader.exceptions import ParseError
from utils import make_url_base


@pytest.fixture(params=[True, False])
def parse(request):
    parse = default_parser('', _lazy=request.param)

    # using the convenience __call__() API instead of parallel(),
    # but we still need access to the ParseResult sometimes
    parse.set_last_result = True

    yield parse


def str_bytes_parser(parse):
    def wrapper(url, file, headers=None):
        if isinstance(file, str):
            file = io.BytesIO(file.encode('utf-8'))
        elif isinstance(file, bytes):
            file = io.BytesIO(file)
        return parse(url, file, headers)

    return wrapper


feedparser_parse = str_bytes_parser(FeedparserParser())
jsonfeed_parse = str_bytes_parser(JSONFeedParser())


def _make_relative_path_url(**_):
    def make_url(feed_path):
        return str(feed_path.relative_to(feed_path.parent.parent))

    return make_url


make_relative_path_url = pytest.fixture(_make_relative_path_url)


def _make_absolute_path_url(**_):
    def make_url(feed_path):
        return str(feed_path)

    return make_url


def _make_http_url(requests_mock, **_):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.name
        headers = {'Hello': 'World'}
        if feed_path.suffix == '.rss':
            headers['Content-Type'] = 'application/rss+xml'
        elif feed_path.suffix == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        elif feed_path.suffix == '.json':
            headers['Content-Type'] = 'application/feed+json'
        with open(str(feed_path), 'rb') as f:
            body = f.read()
        requests_mock.get(url, content=body, headers=headers)
        return url

    return make_url


make_http_url = pytest.fixture(_make_http_url)


def _make_https_url(requests_mock, **_):
    def make_url(feed_path):
        url = 'https://example.com/' + feed_path.name
        headers = {'Hello': 'World'}
        if feed_path.suffix == '.rss':
            headers['Content-Type'] = 'application/rss+xml'
        elif feed_path.suffix == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        elif feed_path.suffix == '.json':
            headers['Content-Type'] = 'application/feed+json'
        with open(str(feed_path), 'rb') as f:
            body = f.read()
        requests_mock.get(url, content=body, headers=headers)
        return url

    return make_url


def _make_http_gzip_url(requests_mock, **_):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.name
        headers = {'Hello': 'World'}
        if feed_path.suffix == '.rss':
            headers['Content-Type'] = 'application/rss+xml'
        elif feed_path.suffix == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        elif feed_path.suffix == '.json':
            headers['Content-Type'] = 'application/feed+json'
        headers['Content-Encoding'] = 'gzip'
        with open(str(feed_path), 'rb') as f:
            body = f.read()

        import gzip
        import io

        compressed_file = io.BytesIO()
        gz = gzip.GzipFile(fileobj=compressed_file, mode='wb')
        gz.write(body)
        gz.close()

        requests_mock.get(url, content=compressed_file.getvalue(), headers=headers)
        return url

    return make_url


def _make_http_url_missing_content_type(requests_mock, **_):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.name
        headers = {'Hello': 'World'}
        with open(str(feed_path), 'rb') as f:
            body = f.read()
        requests_mock.get(url, content=body, headers=headers)
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


@pytest.mark.parametrize(
    'feed_type, data_file',
    [(ft, df) for ft in ['rss', 'atom'] for df in ['full', 'empty', 'relative']]
    + [('json', df) for df in ['full', 'empty', 'invalid', '10', 'unknown']],
)
def test_parse(monkeypatch, feed_type, data_file, parse, make_url, data_dir):
    monkeypatch.chdir(data_dir.parent)

    feed_filename = f'{data_file}.{feed_type}'
    # make_url receives an absolute path,
    # and returns a relative-to-cwd or absolute path or a URL.
    feed_url = make_url(data_dir.joinpath(feed_filename))

    # the base of the feed URL, as the parser will set it;
    # the base of files relative to this feed.
    # TODO: why are they different?
    # TODO: this is too magic / circular; it should be easier to understand/explain.
    url_base, rel_base = make_url_base(feed_url)
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(data_dir.joinpath(feed_filename + '.py').read_text(), expected)

    feed, entries, _, _ = parse(feed_url)
    entries = list(entries)

    assert feed == expected['feed']
    assert entries == expected['entries']

    info = parse.last_result.http_info
    if not feed_url.startswith('http'):
        assert info is None
    else:
        assert info.status == 200
        # note the lowercase key
        assert info.headers['hello'] == 'World'


def test_no_mime_type(monkeypatch, parse, make_url, data_dir):
    """Like test_parse with _make_http_url_missing_content_type,
    but with an URL parser.
    """
    monkeypatch.chdir(data_dir.parent)
    feed_path = data_dir.joinpath('custom')
    feed_url = make_url(feed_path)

    def custom_parser(url, file, headers=None):
        return FeedData(url=url, title=file.read().decode('utf-8')), []

    parse.mount_parser_by_url(feed_url, custom_parser)

    feed, entries, _, _ = parse(feed_url)

    with open(str(feed_path), encoding='utf-8') as f:
        expected_feed = FeedData(url=feed_url, title=f.read())

    assert feed == expected_feed
    assert entries == []


def test_feedparser_exceptions(monkeypatch, parse, data_dir):
    """parse() should reraise most feedparser exceptions."""

    feedparser_exception = Exception("whatever")
    old_feedparser_parse = feedparser.parse

    def feedparser_parse(*args, **kwargs):
        rv = old_feedparser_parse(*args, **kwargs)
        rv['bozo'] = 1
        rv['bozo_exception'] = feedparser_exception
        return rv

    monkeypatch.setattr(feedparser, 'parse', feedparser_parse)

    url = str(data_dir.joinpath('full.atom'))
    with pytest.raises(ParseError) as excinfo:
        parse(url)

    assert excinfo.value.__cause__ is feedparser_exception
    assert excinfo.value.url == url
    assert 'while parsing feed' in excinfo.value.message


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

    monkeypatch.setattr(feedparser, 'parse', feedparser_parse)

    with caplog.at_level(logging.WARNING, logger="reader"):
        # shouldn't raise an exception
        parse(str(data_dir.joinpath('full.atom')))

    warnings = [
        message
        for logger, level, message in caplog.record_tuples
        if logger == 'reader' and level == logging.WARNING
    ]
    assert sum('full.atom' in m and exc_cls.__name__ in m for m in warnings) > 0


@pytest.fixture
def make_http_url_bad_status(requests_mock):
    def make_url(feed_path, status):
        url = 'http://example.com/' + feed_path.name
        headers = {'Hello': 'World'}
        requests_mock.get(url, status_code=status, headers=headers)
        return url

    yield make_url


def test_parse_not_modified(monkeypatch, parse, make_http_url_bad_status, data_dir):
    """parse() should return None for unchanged feeds."""
    feed_url = make_http_url_bad_status(data_dir.joinpath('full.atom'), 304)

    assert parse(feed_url) is None

    info = parse.last_result.http_info
    assert info.status == 304
    # note the lowercase key
    assert info.headers['hello'] == 'World'


@pytest.mark.parametrize('status', [404, 503])
def test_parse_bad_status(
    monkeypatch, parse, make_http_url_bad_status, data_dir, status
):
    """parse() should raise ParseError for 4xx or 5xx status codes.
    https://github.com/lemon24/reader/issues/182

    """
    feed_url = make_http_url_bad_status(data_dir.joinpath('full.atom'), status)
    with pytest.raises(ParseError) as excinfo:
        parse(feed_url)

    assert isinstance(excinfo.value.__cause__, requests.HTTPError)
    assert excinfo.value.url == feed_url
    assert 'bad HTTP status code' in excinfo.value.message

    info = parse.last_result.http_info
    assert info.status == status
    # note the lowercase key
    assert info.headers['hello'] == 'World'


@pytest.fixture
def make_http_get_headers_url(requests_mock):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.name
        headers = {}
        if feed_path.suffix == '.rss':
            headers['Content-Type'] = 'application/rss+xml'
        elif feed_path.suffix == '.atom':
            headers['Content-Type'] = 'application/atom+xml'

        def callback(request, context):
            make_url.request_headers = request.headers
            return feed_path.read_text()

        requests_mock.get(url, text=callback, headers=headers)
        return url

    yield make_url


@pytest.mark.parametrize('feed_type', ['rss', 'atom', 'json'])
@pytest.mark.parametrize(
    'caching_info, expected_headers',
    [
        (None, {}),
        ({'etag': 'e'}, {'If-None-Match': 'e'}),
        ({'last-modified': 'lm'}, {'If-Modified-Since': 'lm'}),
        (
            {'etag': 'e', 'last-modified': 'lm'},
            {'If-None-Match': 'e', 'If-Modified-Since': 'lm'},
        ),
    ],
)
def test_parse_sends_etag_last_modified(
    parse,
    make_http_get_headers_url,
    data_dir,
    feed_type,
    caching_info,
    expected_headers,
):
    feed_url = make_http_get_headers_url(data_dir.joinpath('full.' + feed_type))

    parse(feed_url, caching_info)

    headers = make_http_get_headers_url.request_headers
    assert expected_headers.items() <= headers.items()


@pytest.mark.parametrize('feed_type', ['rss', 'atom', 'json'])
@pytest.mark.parametrize(
    'headers, expected_caching_info',
    [
        ({}, None),
        ({'ETag': 'e'}, {'etag': 'e'}),
        ({'Last-Modified': 'lm'}, {'last-modified': 'lm'}),
        ({'ETag': 'e', 'Last-Modified': 'lm'}, {'etag': 'e', 'last-modified': 'lm'}),
    ],
)
def test_parse_returns_etag_last_modified(
    monkeypatch,
    parse,
    make_http_set_headers_url,
    data_dir,
    feed_type,
    headers,
    expected_caching_info,
):
    monkeypatch.chdir(data_dir.parent)

    feed_url = make_http_set_headers_url(
        data_dir.joinpath('full.' + feed_type), headers
    )
    _, _, _, caching_info = parse(feed_url)

    assert caching_info == expected_caching_info


def test_parse_file_returns_etag_last_modified(
    monkeypatch, parse, make_relative_path_url, data_dir
):
    monkeypatch.chdir(data_dir.parent)

    feed_url = make_relative_path_url(data_dir.joinpath('full.atom'))
    _, _, _, caching_info = parse(feed_url)

    assert caching_info == None


@pytest.mark.parametrize('tz', ['UTC', 'Europe/Helsinki'])
# time.tzset() does not exist on Windows
@pytest.mark.skipif("os.name == 'nt'")
def test_parse_local_timezone(monkeypatch_tz, request, parse, tz, data_dir):
    """parse() return the correct dates regardless of the local timezone."""

    feed_path = data_dir.joinpath('full.atom')

    url_base, rel_base = make_url_base(str(feed_path))
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(feed_path.with_suffix('.atom.py').read_text(), expected)

    monkeypatch_tz(tz)
    feed, _, _, _ = parse(str(feed_path))
    assert feed.updated == expected['feed'].updated


def test_parse_response_plugins(monkeypatch, make_http_url, data_dir):
    feed_url = make_http_url(data_dir.joinpath('empty.atom'))
    make_http_url(data_dir.joinpath('full.atom'))

    import requests

    def req_plugin(session, request, **kwargs):
        req_plugin.called = True
        assert request.url == feed_url

    def do_nothing_plugin(session, response, request, **kwargs):
        do_nothing_plugin.called = True
        assert isinstance(session, requests.Session)
        assert isinstance(response, requests.Response)
        assert isinstance(request, requests.Request)
        assert request.url == feed_url

    def rewrite_to_empty_plugin(session, response, request, **kwargs):
        rewrite_to_empty_plugin.called = True
        request.url = request.url.replace('empty', 'full')
        return request

    parse = default_parser()
    parse.session_factory.request_hooks.append(req_plugin)
    parse.session_factory.response_hooks.append(do_nothing_plugin)
    parse.session_factory.response_hooks.append(rewrite_to_empty_plugin)

    feed, _, _, _ = parse(feed_url)
    assert req_plugin.called
    assert do_nothing_plugin.called
    assert rewrite_to_empty_plugin.called
    assert feed.link is not None


@pytest.mark.parametrize('exc_cls', [Exception, OSError])
def test_parse_requests_get_exception(
    monkeypatch, parse, make_http_url, data_dir, exc_cls
):
    feed_url = make_http_url(data_dir.joinpath('full.atom'))
    exc = exc_cls('exc')

    def do_raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr('reader._parser.requests._lazy.SessionWrapper.get', do_raise)

    with pytest.raises(ParseError) as excinfo:
        parse(feed_url)

    assert excinfo.value.__cause__ is exc
    assert excinfo.value.url == feed_url
    assert 'while getting feed' in excinfo.value.message

    assert not hasattr(excinfo.value, 'http_info')

    assert parse.last_result.http_info is None


@pytest.mark.parametrize('exc_cls', [Exception, OSError])
def test_parse_requests_read_exception(
    monkeypatch, parse, make_http_url, data_dir, exc_cls
):
    feed_url = make_http_url(data_dir.joinpath('full.atom'))
    exc = exc_cls('exc')

    def do_raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr('urllib3.response.HTTPResponse.read', do_raise)

    with pytest.raises(ParseError) as excinfo:
        parse(feed_url)

    assert excinfo.value.__cause__ is exc
    assert excinfo.value.url == feed_url
    assert 'while reading feed' in excinfo.value.message

    assert not hasattr(excinfo.value, 'http_info')

    info = parse.last_result.http_info
    assert info.status == 200
    # note the lowercase key
    assert info.headers['hello'] == 'World'


def test_user_agent_default(parse, make_http_get_headers_url, data_dir):
    feed_url = make_http_get_headers_url(data_dir.joinpath('full.atom'))
    parse(feed_url)

    headers = make_http_get_headers_url.request_headers
    assert headers['User-Agent'].startswith('python-requests/')


def test_user_agent_none(parse, make_http_get_headers_url, data_dir):
    feed_url = make_http_get_headers_url(data_dir.joinpath('full.atom'))
    parse.session_factory.user_agent = None
    parse(feed_url)

    headers = make_http_get_headers_url.request_headers
    assert headers['User-Agent'].startswith('python-requests/')


def test_parallel_persistent_session(parse, make_http_url, data_dir):
    sessions = []

    def req_plugin(session, request, **kwargs):
        sessions.append(session)

    parse.session_factory.request_hooks.append(req_plugin)

    feeds = [
        FeedForUpdate(make_http_url(data_dir.joinpath(name)))
        for name in ('empty.atom', 'empty.rss')
    ]
    list(parse.parallel(feeds))

    assert len(sessions) == 2
    assert sessions[0] is sessions[1]


@pytest.mark.parametrize('exc_cls', [Exception, OSError])
def test_feedparser_parse_call(monkeypatch, parse, make_url, data_dir, exc_cls):
    """feedparser.parse must always be called with True
    resolve_relative_uris and sanitize_html.

    https://github.com/lemon24/reader/issues/125#issuecomment-522333200

    """
    exc = exc_cls("whatever")

    def feedparser_parse(*args, **kwargs):
        feedparser_parse.kwargs = kwargs
        raise exc

    monkeypatch.setattr(feedparser, 'parse', feedparser_parse)

    monkeypatch.chdir(data_dir.parent)
    feed_url = make_url(data_dir.joinpath('full.atom'))

    with pytest.raises(ParseError) as excinfo:
        parse(feed_url)
    assert excinfo.value.__cause__ is exc
    assert excinfo.value.url == feed_url
    assert 'during parser' in excinfo.value.message

    assert feedparser_parse.kwargs['resolve_relative_uris'] == True
    assert feedparser_parse.kwargs['sanitize_html'] == True


def test_missing_entry_id():
    """Handle RSS entries without guid.
    https://github.com/lemon24/reader/issues/170

    """
    # For RSS, when id is missing, parse() falls back to link.
    feed, entries = feedparser_parse(
        'url',
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
        """.strip(),
    )
    (entry,) = list(entries)
    assert entry.id == entry.link

    # ... and only link.
    with pytest.raises(ParseError) as excinfo, pytest.warns(ParseError):
        feedparser_parse(
            'url',
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
            """.strip(),
        )
    assert excinfo.value.url == 'url'
    assert 'entry with no id' in excinfo.value.message

    # But we only raise an exception if *all* entries fail, warn otherwise.
    with pytest.warns(ParseError) as warnings:
        feed, entries = feedparser_parse(
            'url',
            """
            <?xml version="1.0" encoding="UTF-8" ?>
            <rss version="2.0">
            <channel>
                <item>
                    <title>Example entry without id or link</title>
                </item>
                <item>
                    <title>Another one</title>
                </item>
                <item>
                    <link>http://www.example.com/blog/post/1</link>
                    <title>Example entry</title>
                </item>
            </channel>
            </rss>
            """.strip(),
        )
    assert [e.title for e in entries] == ["Example entry"]
    assert len(warnings) == 2, warnings
    assert warnings[0].message.url == 'url'
    assert 'entry with no id' in warnings[0].message.message

    # There is no fallback for Atom.
    with pytest.raises(ParseError) as excinfo, pytest.warns(ParseError):
        feedparser_parse(
            'url',
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
            """.strip(),
        )
    assert excinfo.value.url == 'url'
    assert 'entry with no id' in excinfo.value.message

    # Same for JSON Feed.
    with pytest.raises(ParseError) as excinfo:
        jsonfeed_parse(
            'url',
            """
            {
                "version": "https://jsonfeed.org/version/1.1",
                "items": [
                    {"content_text": "content"}
                ]
            }
            """,
        )
    assert excinfo.value.url == 'url'
    assert 'entry with no id' in excinfo.value.message

    # Non-string, non-number id is treated as missing for JSON Feed.
    with pytest.raises(ParseError) as excinfo:
        jsonfeed_parse(
            'url',
            """
            {
                "version": "https://jsonfeed.org/version/1.1",
                "items": [
                    {"id": {"not": "a string"}, "content_text": "content"}
                ]
            }
            """,
        )
    assert excinfo.value.url == 'url'
    assert 'entry with no id' in excinfo.value.message


def test_no_version():
    """Raise ParseError if feedparser can't detect the feed type and
    there's no bozo_exception.

    """
    with pytest.raises(ParseError) as excinfo:
        feedparser_parse(
            'url',
            """
            <?xml version="1.0" encoding="utf-8"?>
            <element>aaa</element>
            """.strip(),
        )
    assert excinfo.value.url == 'url'
    assert 'unknown feed type' in excinfo.value.message

    with pytest.raises(ParseError) as excinfo:
        jsonfeed_parse(
            'url',
            """
            {
                "version": "https://bad.version/",
                "items": [
                    {"id": "1", "content_text": "content"}
                ]
            }
            """,
        )
    assert excinfo.value.url == 'url'
    assert 'missing or bad JSON Feed version' in excinfo.value.message


def test_jsonfeed_invalid_json():
    with pytest.raises(ParseError) as excinfo:
        jsonfeed_parse('url', "malformed JSON")
    assert excinfo.value.url == 'url'
    assert 'invalid JSON' in excinfo.value.message
    assert isinstance(excinfo.value.__cause__, json.JSONDecodeError)


@pytest.fixture
def make_http_set_headers_url(requests_mock):
    def make_url(feed_path, headers=None):
        url = 'http://example.com/' + feed_path.name
        requests_mock.get(url, text=feed_path.read_text(), headers=headers or {})
        return url

    yield make_url


def test_response_headers(monkeypatch, make_http_set_headers_url, parse, data_dir):
    """The parser should pass the response headers it got from requests.get()
    to feedparser.parse().

    """
    mock = MagicMock(wraps=feedparser.parse)
    monkeypatch.setattr(feedparser, 'parse', mock)

    feed_url = make_http_set_headers_url(
        data_dir.joinpath('empty.atom'), {'whatever': 'boo'}
    )
    parse(feed_url)

    assert mock.call_args[1]['response_headers']['whatever'] == 'boo'


def test_default_response_headers(
    monkeypatch, make_http_set_headers_url, parse, data_dir
):
    """The response headers passed to feedparser.parse() should have specific
    headers set even if they weren't present in the requests.get() response.

    """
    mock = MagicMock(wraps=feedparser.parse)
    monkeypatch.setattr(feedparser, 'parse', mock)

    feed_url = make_http_set_headers_url(data_dir.joinpath('empty.atom'))
    parse(feed_url)

    assert mock.call_args[1]['response_headers']['Content-Location'] == feed_url


@pytest.mark.parametrize('scheme', ['', 'file:', 'file:///', 'file://localhost/'])
@pytest.mark.parametrize('relative', [False, True])
def test_feed_root_empty(data_dir, scheme, relative):
    # TODO: this test looks a lot like test_feed_root_nonempty

    if relative and scheme.startswith('file://'):
        pytest.skip("can't have relative URIs with 'file://...'")

    parse = default_parser('')

    # we know this returns the right thing based on all of the tests above
    good_path = data_dir.joinpath('full.rss')
    good_url = str(good_path)
    good_result = parse(good_url)

    test_path = data_dir.joinpath('full.rss')
    if relative:
        test_path = test_path.relative_to(type(data_dir)().absolute())
    test_url = scheme + str(test_path)
    test_result = parse(test_url)

    # sanity check
    assert good_result.feed.url == good_url
    good_entries = list(good_result.entries)
    assert {e.feed_url for e in good_entries} == {
        good_url,
    }

    assert test_result.feed.url == test_url
    test_entries = list(test_result.entries)
    assert {e.feed_url for e in test_entries} == {
        test_url,
    }

    assert test_result.feed == good_result.feed._replace(url=test_url)
    assert test_entries == [e._replace(feed_url=test_url) for e in good_entries]


@pytest.mark.parametrize('scheme', ['', 'file:'])
def test_feed_root_none(data_dir, scheme):
    parse = default_parser(None)
    url = scheme + str(data_dir.joinpath('full.atom'))
    with pytest.raises(ParseError) as excinfo:
        parse(url)
    assert excinfo.value.url == url
    assert 'no retriever' in excinfo.value.message


@pytest.mark.parametrize('scheme', ['', 'file:'])
def test_feed_root_nonempty(data_dir, scheme):
    # we know this returns the right thing based on all of the tests above
    good_url = str(data_dir.joinpath('full.rss'))
    good_result = default_parser('')(good_url)

    test_url = scheme + 'full.rss'
    test_result = default_parser(data_dir)(test_url)

    # sanity check
    assert good_result.feed.url == good_url
    good_entries = list(good_result.entries)
    assert {e.feed_url for e in good_entries} == {
        good_url,
    }

    assert test_result.feed.url == test_url
    test_entries = list(test_result.entries)
    assert {e.feed_url for e in test_entries} == {
        test_url,
    }

    assert test_result.feed == good_result.feed._replace(url=test_url)
    assert test_entries == [e._replace(feed_url=test_url) for e in good_entries]


# os_name, root
RELATIVE_ROOTS = [
    ('nt', 'C:feeds'),
    ('nt', '\\feeds'),
] + [
    (os_name, root)
    for os_name in ['nt', 'posix']
    for root in ['feeds', './feeds', '../feeds']
]


@pytest.mark.parametrize('os_name, root', RELATIVE_ROOTS)
def test_feed_root_relative_root_error(monkeypatch, os_name, root):
    import ntpath
    import posixpath

    monkeypatch.setattr('os.name', os_name)
    monkeypatch.setattr('os.path', {'nt': ntpath, 'posix': posixpath}[os_name])

    with pytest.raises(ValueError) as excinfo:
        try:
            default_parser(root)
        finally:
            # pytest.raises() doesn't interact well with our monkeypatching
            monkeypatch.undo()

    assert 'root must be absolute' in str(excinfo.value)


# reason, [url, ...]
BAD_PATHS_BY_REASON = [
    (
        'path must be relative',
        [
            '/feed.rss',
            'file:/feed.rss',
            'file:///feed.rss',
            'file://localhost/feed.rss',
        ],
    ),
    ('path cannot be outside root', ['../feed.rss', 'file:../feed.rss']),
    ('unknown authority', ['file://feed.rss', 'file://whatever/feed.rss']),
    (
        'unknown scheme',
        [
            'whatever:feed.rss',
            'whatever:/feed.rss',
            'whatever:///feed.rss',
            'whatever://localhost/feed.rss',
        ],
    ),
]

# url, reason
BAD_PATHS = [(url, reason) for reason, urls in BAD_PATHS_BY_REASON for url in urls]


@pytest.mark.parametrize('url, reason', BAD_PATHS)
def test_feed_root_nonenmpty_bad_paths(data_dir, url, reason):
    with pytest.raises(ParseError) as excinfo:
        default_parser(data_dir)(url)
    assert excinfo.value.url == url
    assert reason in excinfo.value.message


BAD_PATHS_WINDOWS_BY_REASON = [
    ('path must not be reserved', ['NUL', 'CON']),
    (
        'path must be relative',
        [
            'C:\\feed.rss',
            'file:/c:/feed.rss',
            'C:feed.rss',
            'file:/c:feed.rss',
            '\\feed.rss',
        ],
    ),
]


BAD_PATHS_WITH_OS = [
    (os_name, url, reason) for os_name in ('nt', 'posix') for url, reason in BAD_PATHS
] + [
    ('nt', url, reason) for reason, urls in BAD_PATHS_WINDOWS_BY_REASON for url in urls
]


@pytest.mark.parametrize('os_name, url, reason', BAD_PATHS_WITH_OS)
def test_normalize_url_errors(monkeypatch, reload_module, os_name, url, reason):
    import ntpath
    import posixpath

    data_dir = {'nt': 'C:\\feeds', 'posix': '/feeds'}[os_name]

    monkeypatch.setattr('os.name', os_name)
    monkeypatch.setattr('os.path', {'nt': ntpath, 'posix': posixpath}[os_name])

    import urllib.request

    # urllib.request differs based on os.name
    reload_module(urllib.request)

    with pytest.raises(ValueError) as excinfo:
        try:
            FileRetriever(data_dir)._normalize_url(url)
        finally:
            # pytest.raises() doesn't interact well with our monkeypatching
            reload_module.undo()

    assert reason in str(excinfo.value)


def test_parser_mount_order():
    parse = Parser()
    parse.mount_parser_by_mime_type('P0', 'one/two;q=0.0')
    parse.mount_parser_by_mime_type('P1', 'one/two')
    parse.mount_parser_by_mime_type('P2', 'one/two;q=0.1')
    parse.mount_parser_by_mime_type('P3', 'one/two;q=0.1')
    parse.mount_parser_by_mime_type('P4', 'one/two;q=0.4')
    parse.mount_parser_by_mime_type('P5', 'one/two;q=0.5')
    parse.mount_parser_by_mime_type('P6', 'one/two;q=0.3')
    assert parse.parsers_by_mime_type == {
        'one/two': [
            (0.1, 'P2'),
            (0.1, 'P3'),
            (0.3, 'P6'),
            (0.4, 'P4'),
            (0.5, 'P5'),
            (1, 'P1'),
        ]
    }


def make_dummy_retriever(name, mime_type='type/subtype', headers=None):
    @contextmanager
    def retriever(url, caching_info, accept):
        retriever.last_accept = accept
        http_info = HTTPInfo(200, headers)
        yield RetrievedFeed(name, mime_type, caching_info, http_info)

    retriever.slow_to_read = False
    return retriever


def make_dummy_parser(prefix='', accept=None):
    def parser(url, file, headers):
        parser.last_headers = headers
        return prefix + file, [url]

    if accept:
        parser.accept = accept

    return parser


def test_parser_selection():
    parse = Parser()

    http_retriever = make_dummy_retriever('http', 'type/http', 'headers')
    parse.mount_retriever('http:', http_retriever)
    file_retriever = make_dummy_retriever('file', 'type/file')
    parse.mount_retriever('file:', file_retriever)
    nomt_retriever = make_dummy_retriever('nomt', None)
    parse.mount_retriever('nomt:', nomt_retriever)
    parse.mount_retriever('unkn:', make_dummy_retriever('unkn', 'type/unknown'))

    http_parser = make_dummy_parser('httpp-', 'type/http')
    parse.mount_parser_by_mime_type(http_parser)
    assert parse('http:one', 'caching') == (
        'httpp-http',
        ['http:one'],
        'type/http',
        'caching',
    )
    assert http_retriever.last_accept == 'type/http'
    assert http_parser.last_headers == 'headers'

    # this should not get in the way of anything else;
    # it's mounted with "o" to check we do exact match, and not prefix match
    url_parser = make_dummy_parser('urlp-')
    parse.mount_parser_by_url('file:o', url_parser)

    with pytest.raises(ParseError) as excinfo:
        parse('file:one', 'caching')
    assert excinfo.value.url == 'file:one'
    assert 'no parser for MIME type' in excinfo.value.message
    assert 'type/file' in excinfo.value.message

    file_parser = make_dummy_parser('filep-')
    parse.mount_parser_by_mime_type(file_parser, 'type/file, text/plain;q=0.8')
    assert parse('file:one', 'caching') == (
        'filep-file',
        ['file:one'],
        'type/file',
        'caching',
    )
    assert file_retriever.last_accept == 'type/http,type/file,text/plain;q=0.8'
    assert file_parser.last_headers is None

    with pytest.raises(ParseError) as excinfo:
        parse('nomt:one')
    assert excinfo.value.url == 'nomt:one'
    assert 'no parser for MIME type' in excinfo.value.message
    assert 'application/octet-stream' in excinfo.value.message

    with pytest.raises(ParseError) as excinfo:
        parse('nomt:one.html')
    assert excinfo.value.url == 'nomt:one.html'
    assert 'no parser for MIME type' in excinfo.value.message
    assert 'text/html' in excinfo.value.message

    with pytest.raises(ParseError) as excinfo:
        parse('unkn:one')
    assert excinfo.value.url == 'unkn:one'
    assert 'no parser for MIME type' in excinfo.value.message
    assert 'type/unknown' in excinfo.value.message

    with pytest.raises(TypeError) as excinfo:
        parse.mount_parser_by_mime_type(make_dummy_parser('fallbackp-'))
    assert "unaware parser" in str(excinfo.value)

    parse.mount_parser_by_mime_type(make_dummy_parser('fallbackp-'), '*/*')
    assert parse('nomt:one') == (
        'fallbackp-nomt',
        ['nomt:one'],
        'application/octet-stream',
        None,
    )
    assert parse('unkn:one') == ('fallbackp-unkn', ['unkn:one'], 'type/unknown', None)
    assert nomt_retriever.last_accept == 'type/http,type/file,text/plain;q=0.8,*/*'

    assert parse('file:o') == ('urlp-file', ['file:o'], 'type/file', None)
    assert file_retriever.last_accept is None

    # this assert is commented because the selected retriever
    # depends on urlunparse() behavior, which in turn depends
    # on the python version (also varies for other major versions):
    #
    # * before 3.12.6:        urlunparse(urlparse('file:o')) -> 'file:///o'
    # * starting with 3.12.6: urlunparse(urlparse('file:o')) -> 'file:o'
    #
    # changed in https://github.com/python/cpython/issues/85110
    #
    # https://github.com/pypa/pip/pull/12964
    # says file:whatever is not a valid file: url,
    # TODO: maybe we should check (and fail) for invalid file: urls

    # assert parse('file:///o') == ('urlp-file', ['file:///o'], 'type/file', None)


def test_retriever_selection():
    parse = Parser()

    parse.mount_retriever('http://', make_dummy_retriever('generic'))
    parse.mount_retriever('http://specific.com', make_dummy_retriever('specific'))
    parse.mount_parser_by_mime_type(make_dummy_parser(), '*/*')

    assert parse('http://generic.com/', None) == (
        'generic',
        ['http://generic.com/'],
        'type/subtype',
        None,
    )
    assert parse('http://specific.com/', 'caching') == (
        'specific',
        ['http://specific.com/'],
        'type/subtype',
        'caching',
    )

    with pytest.raises(ParseError) as excinfo:
        parse('file:unknown')
    assert excinfo.value.url == 'file:unknown'
    assert 'no retriever' in excinfo.value.message


def test_retrieve_bug_bubbles_up_to_caller(parse):
    exc = RuntimeError('whatever')

    def retrieve(*_, **__):
        raise exc

    parse.retrieve = retrieve

    with pytest.raises(RuntimeError) as exc_info:
        parse('http://example.com')
    assert exc_info.value is exc


def test_retrieved_feed_http_info_not_shadowed_by_retrieve_error(parse):
    exc = RetrieveError('x', http_info=HTTPInfo(333, {}))
    cause = ValueError('whatever')

    class file:
        def read(*_):
            raise exc from cause

    @contextmanager
    def retrieve(*_, **__):
        yield RetrievedFeed(file, http_info=HTTPInfo(200, {}), slow_to_read=True)

    parse.retrieve = retrieve

    with pytest.raises(ParseError) as exc_info:
        parse('http://example.com')

    assert type(exc_info.value) is ParseError
    assert exc_info.value.url is exc.url
    assert exc_info.value.message is exc.message
    # not sure how to check the traceback was preserved
    assert exc_info.value.__cause__ is cause

    assert parse.last_result.http_info == HTTPInfo(200, {})


def test_reader_use_system_feedparser(monkeypatch, reload_module):
    import feedparser

    import reader._parser.feedparser
    import reader._vendor.feedparser

    name = 'READER_NO_VENDORED_FEEDPARSER'

    monkeypatch.delenv(name, raising=False)
    reload_module(reader._parser.feedparser)
    assert reader._parser.feedparser.feedparser is reader._vendor.feedparser

    monkeypatch.setenv(name, '0')
    reload_module(reader._parser.feedparser)
    assert reader._parser.feedparser.feedparser is reader._vendor.feedparser

    monkeypatch.setenv(name, '1')
    reload_module(reader._parser.feedparser)
    assert reader._parser.feedparser.feedparser is feedparser
