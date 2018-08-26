from urllib.parse import urlparse
import warnings

import pytest
import py.path
import feedparser

from reader import Feed
from reader.parser import RequestsParser
from reader.exceptions import ParseError, NotModified


@pytest.yield_fixture
def parse():
    parse = RequestsParser()
    parse._verify = False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield parse


@pytest.fixture
def make_relative_path_url(request):
    def make_relative_path_url(feed, feed_dir):
        return feed.url, None
    return make_relative_path_url


@pytest.fixture
def make_absolute_path_url(request):
    def make_absolute_path_url(feed, feed_dir):
        return str(feed_dir.join(feed.url)), None
    return make_absolute_path_url


@pytest.fixture
def make_http_url(request, https=False, gzip_enabled=False):
    def make_http_url(feed, feed_dir):

        from http.server import HTTPServer, SimpleHTTPRequestHandler
        from threading import Thread
        import subprocess
        import ssl
        import gzip, io

        if https:
            subprocess.run(
                "openssl req -new -x509 -keyout server.pem "
                "-out server.pem -days 365 -nodes".split(),
                input=b'\n'*7)

        http_last_modified = 'Thu, 12 Jul 2018 20:14:00 GMT'

        class Handler(SimpleHTTPRequestHandler):
            def date_time_string(self, timestamp=None):
                return http_last_modified

            if gzip_enabled:

                def send_head(self):
                    self.end_headers = lambda: None
                    original_send_header = self.send_header
                    def send_header(keyword, value):
                        if keyword == 'Content-Length':
                            return
                        original_send_header(keyword, value)
                    self.send_header = send_header

                    f = super().send_head()

                    del self.end_headers
                    del self.send_header

                    if f:
                        try:
                            data = f.read()
                        finally:
                            f.close()

                        compressed_file = io.BytesIO()
                        gz = gzip.GzipFile(fileobj=compressed_file, mode='wb')
                        gz.write(data)
                        gz.close()

                        self.send_header('Content-Encoding', 'gzip')
                        self.send_header('Content-Length', str(len(compressed_file.getvalue())))

                        self.end_headers()

                        compressed_file.seek(0)
                        return compressed_file

                    return f

        httpd = HTTPServer(('127.0.0.1', 0), Handler)
        if https:
            httpd.socket = ssl.wrap_socket(
                httpd.socket, certfile='./server.pem', server_side=True)
        request.addfinalizer(httpd.shutdown)

        Thread(target=httpd.serve_forever).start()

        url = "{p}://{s[0]}:{s[1]}/{f.url}".format(
            p=('https' if https else 'http'), s=httpd.server_address, f=feed)
        return url, http_last_modified

    return make_http_url


@pytest.fixture
def make_http_url_304(request):
    def make_http_url(feed, feed_dir):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from threading import Thread

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_error(304)

        httpd = HTTPServer(('127.0.0.1', 0), Handler)
        request.addfinalizer(httpd.shutdown)

        Thread(target=httpd.serve_forever).start()

        url = "http://{s[0]}:{s[1]}/{f.url}".format(
            s=httpd.server_address, f=feed)
        return url, None

    return make_http_url


@pytest.fixture
def make_https_url(request):
    def make_https_url(feed, feed_dir):
        return make_http_url(request, https=True)(feed, feed_dir)
    return make_https_url


@pytest.fixture
def make_http_gzip_url(request):
    def make_http_gzip_url(feed, feed_dir):
        return make_http_url(request, gzip_enabled=True)(feed, feed_dir)
    return make_http_gzip_url


@pytest.fixture(params=[
    make_relative_path_url,
    make_absolute_path_url,
    pytest.param(make_http_url, marks=pytest.mark.slow),
    pytest.param(make_https_url, marks=pytest.mark.slow),
    pytest.param(make_http_gzip_url, marks=pytest.mark.slow),
])
def make_url(request):
    return request.param(request)


@pytest.fixture(params=[
    make_relative_path_url,
    pytest.param(make_http_url, marks=pytest.mark.slow),
])
def make_url_local_remote(request):
    return request.param(request)


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_parse(monkeypatch, tmpdir, feed_type, parse, make_url):
    monkeypatch.chdir(tmpdir)

    data_dir = py.path.local(__file__).dirpath().join('data')
    feed_filename = 'full.{}'.format(feed_type)
    data_dir.join(feed_filename).copy(tmpdir)

    feed_url, expected_http_last_modified = make_url(Feed(feed_filename), tmpdir)

    expected = {}
    exec(data_dir.join(feed_filename + '.py').read(), expected)

    (
        feed,
        entries,
        http_etag,
        http_last_modified,
    ) = parse(feed_url)
    entries = list(entries)

    assert feed == expected['feed']._replace(url=feed_url)
    assert entries == expected['entries']
    assert http_etag is None
    assert http_last_modified == expected_http_last_modified


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_parse_empty(monkeypatch, tmpdir, feed_type, parse, make_relative_path_url):
    make_url = make_relative_path_url
    monkeypatch.chdir(tmpdir)

    data_dir = py.path.local(__file__).dirpath().join('data')
    feed_filename = 'empty.{}'.format(feed_type)
    data_dir.join(feed_filename).copy(tmpdir)

    feed_url, _ = make_url(Feed(feed_filename), tmpdir)

    expected = {}
    exec(data_dir.join(feed_filename + '.py').read(), expected)

    feed, entries, _, _ = parse(feed_url)
    entries = list(entries)

    assert feed == expected['feed']._replace(url=feed_url)
    assert entries == expected['entries']


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_parse_relative_links(monkeypatch, tmpdir, feed_type, parse, make_url_local_remote):
    make_url = make_url_local_remote

    monkeypatch.chdir(tmpdir)

    data_dir = py.path.local(__file__).dirpath().join('data')
    feed_filename = 'relative.{}'.format(feed_type)
    data_dir.join(feed_filename).copy(tmpdir)

    expected = {}
    exec(data_dir.join(feed_filename + '.py').read(), expected)

    feed_url, _ = make_url(Feed(feed_filename), tmpdir)
    parsed_feed, _, _, _ = parse(feed_url)

    assert parsed_feed.link == urlparse(feed_url)._replace(path=expected['feed'].link).geturl()


def test_parse_error(monkeypatch, tmpdir, parse):
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
        parse(str(py.path.local(__file__).dirpath().join('data/full.atom')))

    assert excinfo.value.__cause__ is feedparser_exception


def test_parse_character_encoding_override(monkeypatch, parse):
    """parse() should not reraise feedparser.CharacterEncodingOverride."""

    old_feedparser_parse = feedparser.parse
    def feedparser_parse(*args, **kwargs):
        rv = old_feedparser_parse(*args, **kwargs)
        rv['bozo'] = 1
        rv['bozo_exception'] = feedparser.CharacterEncodingOverride("whatever")
        return rv

    monkeypatch.setattr('feedparser.parse', feedparser_parse)

    # shouldn't raise an exception
    parse(str(py.path.local(__file__).dirpath().join('data/full.atom')))


@pytest.mark.slow
def test_parse_not_modified(monkeypatch, tmpdir, parse, make_http_url_304):
    """parse() should raise NotModified for unchanged feeds."""

    monkeypatch.chdir(tmpdir)
    py.path.local(__file__).dirpath().join('data/full.atom').copy(tmpdir)

    feed_url, _ = make_http_url_304(Feed('full.atom'), tmpdir)

    with pytest.raises(NotModified):
        parse(feed_url)


@pytest.fixture
def make_http_get_headers_url(request):
    def make_http_url(feed, feed_dir):
        from http.server import HTTPServer, SimpleHTTPRequestHandler
        from threading import Thread

        class Handler(SimpleHTTPRequestHandler):
            def send_response(self, *args, **kwargs):
                make_http_url.headers = self.headers
                return super().send_response(*args, **kwargs)

        httpd = HTTPServer(('127.0.0.1', 0), Handler)
        request.addfinalizer(httpd.shutdown)

        Thread(target=httpd.serve_forever).start()

        url = "http://{s[0]}:{s[1]}/{f.url}".format(
            s=httpd.server_address, f=feed)
        return url, None

    return make_http_url


@pytest.mark.slow
def test_parse_etag_last_modified(monkeypatch, tmpdir, parse, make_http_get_headers_url):
    monkeypatch.chdir(tmpdir)
    py.path.local(__file__).dirpath().join('data/full.atom').copy(tmpdir)

    feed_url, _ = make_http_get_headers_url(Feed('full.atom'), tmpdir)
    parse(feed_url, 'etag', 'last_modified')

    assert make_http_get_headers_url.headers.get('If-None-Match') == 'etag'
    assert make_http_get_headers_url.headers.get('If-Modified-Since') == 'last_modified'


@pytest.mark.parametrize('tz', ['UTC', 'Europe/Helsinki'])
def test_parse_local_timezone(monkeypatch, request, parse, tz):
    """parse() return the correct dates regardless of the local timezone."""

    feed_path = py.path.local(__file__).dirpath().join('data/full.atom')

    expected = {}
    exec(feed_path.new(ext='.atom.py').read(), expected)

    import time
    request.addfinalizer(time.tzset)
    monkeypatch.setenv('TZ', tz)
    time.tzset()
    feed = parse(str(feed_path))[0]
    assert feed.updated == expected['feed'].updated


@pytest.mark.slow
def test_parse_response_plugins(monkeypatch, tmpdir, make_http_url):
    monkeypatch.chdir(py.path.local(__file__).dirpath().join('data'))

    feed_url, _ = make_http_url(Feed('empty.atom'), tmpdir)

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

    parse = RequestsParser()
    parse.response_plugins.append(do_nothing_plugin)
    parse.response_plugins.append(rewrite_to_empty_plugin)

    feed, _, _, _ = parse(feed_url)
    assert do_nothing_plugin.called
    assert rewrite_to_empty_plugin.called
    assert feed.link is not None
    print('---', feed)


def test_parse_requests_exception(monkeypatch, parse):
    exc = Exception('exc')
    def raise_exc():
        raise exc

    import requests
    monkeypatch.setattr(requests, 'Session', raise_exc)

    with pytest.raises(ParseError) as excinfo:
        parse('http://example.com')

    assert excinfo.value.__cause__ is exc

