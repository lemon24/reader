import socketserver
import threading

import pytest

from reader import USER_AGENT
from utils import make_url_base
from utils import utc_datetime


@pytest.fixture
def server(request):
    server = HTTPServer(('127.0.0.1', 0))
    thread = threading.Thread(target=server.serve_forever, args=(0.005,))
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()


class HTTPServer(socketserver.TCPServer):

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            lines = iter(self.rfile.readline, b'\r\n')
            self.server.request = parse_request(b''.join(lines))
            self.wfile.writelines(self.server.response)

    def __init__(self, server_address, bind_and_activate=True):
        super().__init__(server_address, self.Handler, bind_and_activate)
        self.response = None
        self.request = None

    @property
    def url(self):
        return f"http://{self.server_address[0]}:{self.server_address[1]}/"

    def set_response(self, *args, **kwargs):
        self.response = list(generate_response(*args, **kwargs))


def parse_request(request):
    header, _, body = request.partition(b'\r\n\r\n')
    lines = header.removesuffix(b'\r\n').split(b'\r\n')
    headers = dict(l.partition(b': ')[::2] for l in lines[1:])
    return lines[0], headers, body


def generate_response(body=b'', *, status='200 OK', **headers):
    def ensure_bytes(s):
        return s.encode() if isinstance(s, str) else s

    body = ensure_bytes(body)
    processed_headers = {}
    if body:
        processed_headers['Content-Length'] = str(len(body))
        processed_headers['Content-Type'] = 'text/xml'
    for name, value in headers.items():
        processed_headers[name.replace('_', '-')] = value

    yield b'HTTP/1.1 ' + ensure_bytes(status) + b'\r\n'
    for name, value in processed_headers.items():
        yield ensure_bytes(name) + b': ' + ensure_bytes(value) + b'\r\n'
    yield b'\r\n'
    yield body


@pytest.mark.parametrize('feed_type', ['rss', 'atom', 'json'])
def test_local(reader, feed_type, data_dir, monkeypatch_datetime):
    datetime = monkeypatch_datetime('reader.core.datetime')

    feed_filename = f'full.{feed_type}'
    feed_url = str(data_dir.joinpath(feed_filename))

    datetime.now.set(datetime(2010, 1, 1))
    reader.add_feed(feed_url)
    datetime.now.set(datetime(2010, 1, 2))
    reader.update_feeds()

    (feed,) = reader.get_feeds()
    entries = sorted(reader.get_entries(), key=lambda e: e.id)

    url_base, rel_base = make_url_base(feed_url)
    expected = {'url_base': url_base, 'rel_base': rel_base}
    exec(data_dir.joinpath(feed_filename + '.py').read_text(), expected)

    expected_feed = expected['feed'].as_feed(
        added=utc_datetime(2010, 1, 1),
        last_updated=utc_datetime(2010, 1, 2),
        last_retrieved=utc_datetime(2010, 1, 2),
        update_after=utc_datetime(2010, 1, 2, 1),
    )

    assert feed == expected_feed
    assert entries == [
        e.as_entry(
            feed=feed,
            added=utc_datetime(2010, 1, 2),
            last_updated=utc_datetime(2010, 1, 2),
        )
        for e in sorted(expected['entries'], key=lambda e: e.id)
    ]

    # TODO: same tests, but with http server


@pytest.mark.slow
def test_fixed_headers(reader, data_dir, server):
    reader.add_feed(server.url)

    server.set_response(data_dir.joinpath('empty.atom').read_text())
    reader.update_feed(server.url)

    _, headers, _ = server.request

    assert headers[b'User-Agent'] == USER_AGENT.encode()
    assert headers[b'User-Agent'].startswith(b'python-reader/')
    assert headers[b'User-Agent'].endswith(b' (+https://github.com/lemon24/reader)')

    assert headers[b'Accept'] == (
        b'application/atom+xml,application/rdf+xml,application/rss+xml'
        b',application/x-netcdf,application/feed+json,application/xml'
        b';q=0.9,application/json'
        b';q=0.9,text/xml'
        b';q=0.2,*/*'
        b';q=0.1'
    )

    assert headers[b'A-IM'] == b'feed'


@pytest.mark.slow
@pytest.mark.noscheduled
def test_conditional_requests(reader, data_dir, server):
    """Check ETag / Last-Modified are sent back, at the wire level.

    Ensures https://rachelbythebay.com/w/2023/01/18/http/ cannot happen.

    """
    etag = b'"00000-67890abcdef12"'
    last_modified = b'Thu, 1 Jan 2020 00:00:00 GMT'

    reader.add_feed(server.url)

    # server response with caching headers
    server.set_response(
        data_dir.joinpath('full.atom').read_text(),
        ETag=etag,
        Last_Modified=last_modified,
    )
    assert reader.update_feed(server.url).new == 5
    request_line, headers, body = server.request
    assert request_line == b'GET / HTTP/1.1'
    assert body == b''
    assert b'If-None-Match' not in headers
    assert b'If-Modified-Since' not in headers

    # assert caching headers are used
    server.set_response(status='304 Not Modified')
    assert reader.update_feed(server.url) is None
    request_line, headers, body = server.request
    assert headers[b'If-None-Match'] == etag
    assert headers[b'If-Modified-Since'] == last_modified

    # server responds with new caching headers
    server.set_response(
        data_dir.joinpath('empty.atom').read_text(),
        ETag=b'"11111-67890abcdef12"',
        Last_Modified=b'Thu, 1 Jan 2020 11:11:11 GMT',
    )
    assert reader.update_feed(server.url).new == 0
    request_line, headers, body = server.request
    assert headers[b'If-None-Match'] == etag
    assert headers[b'If-Modified-Since'] == last_modified

    # assert new caching headers are used
    server.set_response(status='304 Not Modified')
    assert reader.update_feed(server.url) is None
    request_line, headers, body = server.request
    assert headers[b'If-None-Match'] == b'"11111-67890abcdef12"'
    assert headers[b'If-Modified-Since'] == b'Thu, 1 Jan 2020 11:11:11 GMT'


@pytest.mark.slow
def test_cache_control(reader, data_dir, server, monkeypatch_datetime):
    datetime = monkeypatch_datetime('reader.core.datetime')
    datetime.now.set(datetime(2010, 1, 1))
    reader.add_feed(server.url)

    server.set_response(
        data_dir.joinpath('empty.atom').read_text(),
        Cache_Control=f'max-age={3600 * 12}',
    )

    def update():
        return set(dict(reader.update_feeds_iter(scheduled=True)))

    datetime.now.set(datetime(2010, 1, 2))
    assert update() == {server.url}

    datetime.now.set(datetime(2010, 1, 2, 12, 59, 59))
    assert update() == set()

    datetime.now.set(datetime(2010, 1, 2, 13))
    assert update() == {server.url}
