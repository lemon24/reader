import io
import json
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock

import feedparser
import pytest
import requests
from utils import make_url_base

from reader import Feed
from reader._parser import default_parser
from reader._parser import FeedparserParser
from reader._parser import FileRetriever
from reader._parser import JSONFeedParser
from reader._parser import Parser
from reader._parser import RetrieveResult
from reader._parser import SessionWrapper
from reader._types import FeedData
from reader.exceptions import ParseError


@pytest.fixture
def parse():
    parse = default_parser('')
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
        return feed_path.relto(feed_path.join('../..'))

    return make_url


make_relative_path_url = pytest.fixture(_make_relative_path_url)


def _make_absolute_path_url(**_):
    def make_url(feed_path):
        return str(feed_path)

    return make_url


def _make_http_url(requests_mock, **_):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        headers = {}
        if feed_path.ext == '.rss':
            headers['Content-Type'] = 'application/rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        elif feed_path.ext == '.json':
            headers['Content-Type'] = 'application/feed+json'
        with open(str(feed_path), 'rb') as f:
            body = f.read()
        requests_mock.get(url, content=body, headers=headers)
        return url

    return make_url


make_http_url = pytest.fixture(_make_http_url)


def _make_https_url(requests_mock, **_):
    def make_url(feed_path):
        url = 'https://example.com/' + feed_path.basename
        headers = {}
        if feed_path.ext == '.rss':
            headers['Content-Type'] = 'application/rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        elif feed_path.ext == '.json':
            headers['Content-Type'] = 'application/feed+json'
        with open(str(feed_path), 'rb') as f:
            body = f.read()
        requests_mock.get(url, content=body, headers=headers)
        return url

    return make_url


def _make_http_gzip_url(requests_mock, **_):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        headers = {}
        if feed_path.ext == '.rss':
            headers['Content-Type'] = 'application/rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        elif feed_path.ext == '.json':
            headers['Content-Type'] = 'application/feed+json'
        headers['Content-Encoding'] = 'gzip'
        with open(str(feed_path), 'rb') as f:
            body = f.read()

        import io, gzip

        compressed_file = io.BytesIO()
        gz = gzip.GzipFile(fileobj=compressed_file, mode='wb')
        gz.write(body)
        gz.close()

        requests_mock.get(url, content=compressed_file.getvalue(), headers=headers)
        return url

    return make_url


def _make_http_url_missing_content_type(requests_mock, **_):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        with open(str(feed_path), 'rb') as f:
            body = f.read()
        requests_mock.get(url, content=body)
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
    + [('json', df) for df in ['full', 'empty', 'invalid']],
)
def test_parse(monkeypatch, feed_type, data_file, parse, make_url, data_dir):
    monkeypatch.chdir(data_dir.dirname)

    feed_filename = '{}.{}'.format(data_file, feed_type)
    # make_url receives an absolute path,
    # and returns a relative-to-cwd or absolute path or a URL.
    feed_url = make_url(data_dir.join(feed_filename))

    # the base of the feed URL, as the parser will set it;
    # the base of files relative to this feed.
    # TODO: why are they different?
    # TODO: this is too magic / circular; it should be easier to understand/explain.
    url_base, rel_base = make_url_base(feed_url)
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(data_dir.join(feed_filename + '.py').read(), expected)

    feed, entries, _, _ = parse(feed_url)
    entries = list(entries)

    assert feed == expected['feed']
    assert entries == expected['entries']


def test_no_mime_type(monkeypatch, parse, make_url, data_dir):
    """Like test_parse with _make_http_url_missing_content_type,
    but with an URL parser.
    """
    monkeypatch.chdir(data_dir.dirname)
    feed_path = data_dir.join('custom')
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

    url = str(data_dir.join('full.atom'))
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
        parse(str(data_dir.join('full.atom')))

    warnings = [
        message
        for logger, level, message in caplog.record_tuples
        if logger == 'reader' and level == logging.WARNING
    ]
    assert sum('full.atom' in m and exc_cls.__name__ in m for m in warnings) > 0


@pytest.fixture
def make_http_url_bad_status(requests_mock):
    def make_url(feed_path, status):
        url = 'http://example.com/' + feed_path.basename
        requests_mock.get(url, status_code=status)
        return url

    yield make_url


def test_parse_not_modified(monkeypatch, parse, make_http_url_bad_status, data_dir):
    """parse() should return None for unchanged feeds."""
    feed_url = make_http_url_bad_status(data_dir.join('full.atom'), 304)
    assert parse(feed_url) is None


@pytest.mark.parametrize('status', [404, 503])
def test_parse_bad_status(
    monkeypatch, parse, make_http_url_bad_status, data_dir, status
):
    """parse() should raise ParseError for 4xx or 5xx status codes.
    https://github.com/lemon24/reader/issues/182

    """
    feed_url = make_http_url_bad_status(data_dir.join('full.atom'), status)
    with pytest.raises(ParseError) as excinfo:
        parse(feed_url)

    assert isinstance(excinfo.value.__cause__, requests.HTTPError)
    assert excinfo.value.url == feed_url
    assert 'bad HTTP status code' in excinfo.value.message


@pytest.fixture
def make_http_get_headers_url(requests_mock):
    def make_url(feed_path):
        url = 'http://example.com/' + feed_path.basename
        headers = {}
        if feed_path.ext == '.rss':
            headers['Content-Type'] = 'application/rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'

        def callback(request, context):
            make_url.request_headers = request.headers
            return feed_path.read()

        requests_mock.get(url, text=callback, headers=headers)
        return url

    yield make_url


@pytest.mark.parametrize('feed_type', ['rss', 'atom', 'json'])
def test_parse_sends_etag_last_modified(
    parse,
    make_http_get_headers_url,
    data_dir,
    feed_type,
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
            headers['Content-Type'] = 'application/rss+xml'
        elif feed_path.ext == '.atom':
            headers['Content-Type'] = 'application/atom+xml'
        requests_mock.get(url, text=feed_path.read(), headers=headers)
        return url

    yield make_url


@pytest.mark.parametrize('feed_type', ['rss', 'atom', 'json'])
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
# timt.tzset() does not exist on Windows
@pytest.mark.skipif("os.name == 'nt'")
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
    parse.session_hooks.request.append(req_plugin)
    parse.session_hooks.response.append(do_nothing_plugin)
    parse.session_hooks.response.append(rewrite_to_empty_plugin)

    feed, _, _, _ = parse(feed_url)
    assert req_plugin.called
    assert do_nothing_plugin.called
    assert rewrite_to_empty_plugin.called
    assert feed.link is not None


@pytest.mark.parametrize('exc_cls', [Exception, OSError])
def test_parse_requests_exception(monkeypatch, exc_cls):
    exc = exc_cls('exc')

    class BadWrapper(SessionWrapper):
        def get(self, *args, **kwargs):
            raise exc

    monkeypatch.setattr('reader._parser.Parser.make_session', BadWrapper)

    with pytest.raises(ParseError) as excinfo:
        default_parser('')('http://example.com')

    assert excinfo.value.__cause__ is exc
    assert excinfo.value.url == 'http://example.com'
    assert 'while getting feed' in excinfo.value.message


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

    monkeypatch.chdir(data_dir.dirname)
    feed_url = make_url(data_dir.join('full.atom'))

    with pytest.raises(ParseError) as excinfo:
        parse(feed_url)
    assert excinfo.value.__cause__ is exc
    assert excinfo.value.url == feed_url
    assert 'while reading feed' in excinfo.value.message

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
    with pytest.raises(ParseError) as excinfo:
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

    # There is no fallback for Atom.
    with pytest.raises(ParseError) as excinfo:
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
        url = 'http://example.com/' + feed_path.basename
        requests_mock.get(url, text=feed_path.read(), headers=headers or {})
        return url

    yield make_url


def test_response_headers(monkeypatch, make_http_set_headers_url, parse, data_dir):
    """The parser should pass the response headers it got from requests.get()
    to feedparser.parse().

    """
    mock = MagicMock(wraps=feedparser.parse)
    monkeypatch.setattr(feedparser, 'parse', mock)

    feed_url = make_http_set_headers_url(
        data_dir.join('empty.atom'), {'whatever': 'boo'}
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

    feed_url = make_http_set_headers_url(data_dir.join('empty.atom'))
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
    good_path = data_dir.join('full.rss')
    good_url = str(good_path)
    good_result = parse(good_url)

    test_path = data_dir.join('full.rss')
    if relative:
        test_path = test_path.relto(type(data_dir)())
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
    url = scheme + str(data_dir.join('full.atom'))
    with pytest.raises(ParseError) as excinfo:
        parse(url)
    assert excinfo.value.url == url
    assert 'no retriever' in excinfo.value.message


@pytest.mark.parametrize('scheme', ['', 'file:'])
def test_feed_root_nonempty(data_dir, scheme):
    # we know this returns the right thing based on all of the tests above
    good_url = str(data_dir.join('full.rss'))
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
RELATIVE_ROOTS = [('nt', 'C:feeds'), ('nt', '\\feeds'),] + [
    (os_name, root)
    for os_name in ['nt', 'posix']
    for root in ['feeds', './feeds', '../feeds']
]


@pytest.mark.parametrize('os_name, root', RELATIVE_ROOTS)
def test_feed_root_relative_root_error(monkeypatch, os_name, root):
    import ntpath, posixpath

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
    ('device file', ['NUL', 'CON']),
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
    import ntpath, posixpath, urllib.request

    data_dir = {'nt': 'C:\\feeds', 'posix': '/feeds'}[os_name]

    monkeypatch.setattr('os.name', os_name)
    monkeypatch.setattr('os.path', {'nt': ntpath, 'posix': posixpath}[os_name])
    # urllib.request.url2pathname differs based on os.name
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
    def retriever(url, http_etag, http_last_modified, http_accept):
        retriever.last_http_accept = http_accept
        yield RetrieveResult(name, mime_type, http_etag, http_last_modified, headers)

    return retriever


def make_dummy_parser(prefix='', http_accept=None):
    def parser(url, file, headers):
        parser.last_headers = headers
        return prefix + file, url

    if http_accept:
        parser.http_accept = http_accept

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
    assert parse('http:one', 'etag', None) == (
        'httpp-http',
        'http:one',
        'etag',
        None,
    )
    assert http_retriever.last_http_accept == 'type/http'
    assert http_parser.last_headers == 'headers'

    # this should not get in the way of anything else;
    # it's mounted with "o" to check we do exact match, and not prefix match
    url_parser = make_dummy_parser('urlp-')
    parse.mount_parser_by_url('file:o', url_parser)

    with pytest.raises(ParseError) as excinfo:
        parse('file:one', None, 'last-modified')
    assert excinfo.value.url == 'file:one'
    assert 'no parser for MIME type' in excinfo.value.message
    assert 'type/file' in excinfo.value.message

    file_parser = make_dummy_parser('filep-')
    parse.mount_parser_by_mime_type(file_parser, 'type/file, text/plain;q=0.8')
    assert parse('file:one', None, 'last-modified') == (
        'filep-file',
        'file:one',
        None,
        'last-modified',
    )
    assert file_retriever.last_http_accept == 'type/http,type/file,text/plain;q=0.8'
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
    assert parse('nomt:one') == ('fallbackp-nomt', 'nomt:one', None, None)
    assert parse('unkn:one') == ('fallbackp-unkn', 'unkn:one', None, None)
    assert nomt_retriever.last_http_accept == 'type/http,type/file,*/*,text/plain;q=0.8'

    assert parse('file:o') == ('urlp-file', 'file:o', None, None)
    assert file_retriever.last_http_accept is None
    assert parse('file:///o') == ('urlp-file', 'file:///o', None, None)


def test_retriever_selection():
    parse = Parser()

    parse.mount_retriever('http://', make_dummy_retriever('generic'))
    parse.mount_retriever('http://specific.com', make_dummy_retriever('specific'))
    parse.mount_parser_by_mime_type(make_dummy_parser(), '*/*')

    assert parse('http://generic.com/', 'etag', None) == (
        'generic',
        'http://generic.com/',
        'etag',
        None,
    )
    assert parse('http://specific.com/', None, 'last-modified') == (
        'specific',
        'http://specific.com/',
        None,
        'last-modified',
    )

    with pytest.raises(ParseError) as excinfo:
        parse('file:unknown')
    assert excinfo.value.url == 'file:unknown'
    assert 'no retriever' in excinfo.value.message
