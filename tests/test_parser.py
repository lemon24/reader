from datetime import datetime
from functools import partial
from urllib.parse import urlparse
import warnings

import pytest
import py.path
import feedgen.feed
import feedparser

from reader import Feed
from reader.parser import parse as reader_parse
from reader.exceptions import ParseError, NotModified
from reader.types import Content, Enclosure

from fakeparser import Parser


def write_feed(type, feed, entries):

    def utc(dt):
        import datetime
        return dt.replace(tzinfo=datetime.timezone(datetime.timedelta()))

    fg = feedgen.feed.FeedGenerator()
    fg.load_extension('podcast')

    if type == 'atom':
        fg.id(feed.link)
    fg.title(feed.title)
    if feed.link:
        fg.link(href=feed.link)
    if feed.updated:
        fg.updated(utc(feed.updated))
    if feed.author:
        if type == 'atom':
            fg.author({'name': feed.author})
        elif type == 'rss':
            fg.podcast.itunes_author(feed.author)
    if type == 'rss':
        fg.description('description')

    for entry in entries:
        fe = fg.add_entry()
        fe.id(entry.id)
        fe.title(entry.title)
        if entry.link:
            fe.link(href=entry.link)
        if entry.updated:
            if type == 'atom':
                fe.updated(utc(entry.updated))
            elif type == 'rss':
                fe.published(utc(entry.updated))
        if entry.author:
            if type == 'atom':
                fe.author({'name': entry.author})
            elif type == 'rss':
                fe.podcast.itunes_author(entry.author)
        if entry.published:
            if type == 'atom':
                fe.published(utc(entry.published))
            elif type == 'rss':
                assert False, "RSS doesn't support published"

        for enclosure in entry.enclosures or ():
            fe.enclosure(enclosure.href, str(enclosure.length), enclosure.type)

        if type == 'atom':
            if entry.content:
                assert len(entry.content) == 1, "feedgen only supports 1 content"
                content = entry.content[0]
                fe.content(content.value, type=content.type)

        elif type == 'rss':
            assert not entry.content, "feedgen forces content to summary"
        if entry.summary:
            fe.summary(entry.summary)

    if type == 'atom':
        fg.atom_file(feed.url, pretty=True)
    elif type == 'rss':
        fg.rss_file(feed.url, pretty=True)


@pytest.yield_fixture
def parse(monkeypatch):
    monkeypatch.setattr(reader_parse, '_verify', False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield reader_parse


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
    #entries = sorted(entries, key=lambda e: e.updated)
    entries = list(entries)

    assert feed == expected['feed']._replace(url=feed_url)
    assert entries == expected['entries']
    assert http_etag is None
    assert http_last_modified == expected_http_last_modified


@pytest.mark.parametrize('feed_type', ['rss', 'atom'])
def test_parse_relative_links(monkeypatch, tmpdir, feed_type, parse, make_url_local_remote):
    make_url = make_url_local_remote

    monkeypatch.chdir(tmpdir)

    parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1), link="file.html")
    write_feed(feed_type, feed, [])

    feed_url, _ = make_url(feed, tmpdir)
    parsed_feed, _, _, _ = parse(feed_url)

    assert parsed_feed.link == urlparse(feed_url)._replace(path='file.html').geturl()


def test_parse_error(monkeypatch, tmpdir, parse):
    """parse() should reraise most feedparser exceptions."""

    monkeypatch.chdir(tmpdir)

    parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    write_feed('atom', feed, [])

    feedparser_exception = Exception("whatever")
    old_feedparser_parse = feedparser.parse
    def feedparser_parse(*args, **kwargs):
        rv = old_feedparser_parse(*args, **kwargs)
        rv['bozo'] = 1
        rv['bozo_exception'] = feedparser_exception
        return rv

    monkeypatch.setattr('feedparser.parse', feedparser_parse)

    with pytest.raises(ParseError) as excinfo:
        parse(feed.url)

    assert excinfo.value.__cause__ is feedparser_exception


def test_parse_character_encoding_override(monkeypatch, tmpdir, parse):
    """parse() should not reraise feedparser.CharacterEncodingOverride."""

    monkeypatch.chdir(tmpdir)

    parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    write_feed('atom', feed, [])

    old_feedparser_parse = feedparser.parse
    def feedparser_parse(*args, **kwargs):
        rv = old_feedparser_parse(*args, **kwargs)
        rv['bozo'] = 1
        rv['bozo_exception'] = feedparser.CharacterEncodingOverride("whatever")
        return rv

    monkeypatch.setattr('feedparser.parse', feedparser_parse)

    # shouldn't raise an exception
    parse(feed.url)


@pytest.mark.slow
def test_parse_not_modified(monkeypatch, tmpdir, parse, make_http_url_304):
    """parse() should raise NotModified for unchanged feeds."""

    monkeypatch.chdir(tmpdir)

    parser = Parser()

    feed = parser.feed(1, datetime(2010, 1, 1))
    write_feed('atom', feed, [])

    feed_url, _ = make_http_url_304(feed, tmpdir)

    with pytest.raises(NotModified):
        parse(feed_url)


@pytest.mark.parametrize('tz', ['UTC', 'Europe/Helsinki'])
def test_parse_local_timezone(monkeypatch, request, parse, tmpdir, tz):
    """parse() return the correct dates regardless of the local timezone."""
    monkeypatch.chdir(tmpdir)

    parser = Parser()

    feed = parser.feed(1, datetime(2018, 7, 7))
    write_feed('atom', feed, [])

    import time
    request.addfinalizer(time.tzset)
    monkeypatch.setenv('TZ', tz)
    time.tzset()
    parsed_feed = parse(feed.url)[0]
    assert feed.updated == parsed_feed.updated


