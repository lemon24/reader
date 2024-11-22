import socketserver
import threading

import pytest

from reader import USER_AGENT
from utils import make_url_base
from utils import utc_datetime


class Server(socketserver.TCPServer):
    def __init__(self, *args):
        super().__init__(*args)
        self.response = b''
        self.request = None

    @property
    def url(self):
        return f"http://{self.server_address[0]}:{self.server_address[1]}/"

    def set_response(self, *args, **kwargs):
        self.response = make_response(*args, **kwargs)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        lines = []
        while True:
            line = self.rfile.readline()
            lines.append(line)
            if not line.rstrip():
                break
        self.server.request = parse_request(b''.join(lines))
        self.wfile.write(self.server.response)


@pytest.fixture
def server(request):
    server = Server(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()


def make_response(*args, **kwargs):
    """Simple HTTP response.

    >>> print(make_response('body', 'Thu, 1 Jan 2020 00:00:00 GMT', '"12345-67890abcdef12"').decode(), end='<eof>\n')
    HTTP/1.1 200 OK
    Last-Modified: Thu, 1 Jan 2020 00:00:00 GMT
    ETag: "12345-67890abcdef12"
    Content-Length: 4
    Content-Type: text/xml

    body<eof>
    """
    return b''.join(generate_response(*args, **kwargs))


def generate_response(body='', etag=None, last_modified=None, status_line='200 OK'):
    yield b'HTTP/1.1 ' + ensure_bytes(status_line) + b'\r\n'
    if etag:
        yield b'ETag: ' + ensure_bytes(etag) + b'\r\n'
    if last_modified:
        yield b'Last-Modified: ' + ensure_bytes(last_modified) + b'\r\n'
    body = ensure_bytes(body)
    yield b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
    yield b'Content-Type: text/xml\r\n'
    yield b'\r\n'
    yield body


def ensure_bytes(s):
    if not isinstance(s, bytes):
        return s.encode()
    return s


def parse_request(request):
    header, _, body = request.partition(b'\r\n\r\n')
    lines = header.split(b'\r\n')
    headers = dict(l.partition(b': ')[::2] for l in lines[1:])
    return lines[0], headers, body


@pytest.mark.parametrize('feed_type', ['rss', 'atom', 'json'])
def test_local(reader, feed_type, data_dir, monkeypatch):
    feed_filename = f'full.{feed_type}'
    feed_url = str(data_dir.joinpath(feed_filename))

    # TODO: maybe don't mock, and just check datetimes are in the correct order

    # On CPython, we can't mock datetime.datetime.now because
    # datetime.datetime is a built-in/extension type; we can mock the class.
    # On PyPy, we can mock the class, but it results in weird type errors
    # when the mock/subclass and original datetime class interact.

    from datetime import datetime

    try:
        # if we can set attributes on the class, we just patch now() directly
        # (we don't use monkeypatch because it breaks cleanup if it doesn't work)
        datetime.now = datetime.now
        datetime_mock = datetime
    except TypeError:
        # otherwise, we monkeypatch the datetime class on the module
        class datetime_mock(datetime):
            pass

        # reader.core must "from datetime import datetime" !
        monkeypatch.setattr('reader.core.datetime', datetime_mock)

    monkeypatch.setattr(
        datetime_mock, 'now', lambda tz=None: datetime(2010, 1, 1, tzinfo=tz)
    )
    reader.add_feed(feed_url)
    monkeypatch.setattr(
        datetime_mock, 'now', lambda tz=None: datetime(2010, 1, 2, tzinfo=tz)
    )
    reader.update_feeds()
    monkeypatch.undo()

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
def test_etag_last_modified(reader, data_dir, server):
    """Check ETag / Last-Modified are sent back, at the wire level.

    Ensures https://rachelbythebay.com/w/2023/01/18/http/ cannot happen.

    """
    etag = b'"00000-67890abcdef12"'
    last_modified = b'Thu, 1 Jan 2020 00:00:00 GMT'

    server.set_response(data_dir.joinpath('full.atom').read_text(), etag, last_modified)
    url = server.url

    reader.add_feed(url)

    # server response with caching headers
    assert reader.update_feed(url).new == 5
    request_line, headers, body = server.request
    assert request_line == b'GET / HTTP/1.1'
    assert body == b''
    assert b'If-None-Match' not in headers
    assert b'If-Modified-Since' not in headers

    # assert caching headers are used
    server.set_response(status_line='304 Not Modified')
    assert reader.update_feed(url) is None
    request_line, headers, body = server.request
    assert request_line == b'GET / HTTP/1.1'
    assert body == b''
    assert headers[b'If-None-Match'] == etag
    assert headers[b'If-Modified-Since'] == last_modified

    ua = headers[b'User-Agent']
    assert ua == USER_AGENT.encode()
    assert ua.startswith(b'python-reader/')
    assert ua.endswith(b' (+https://github.com/lemon24/reader)')

    # TODO: since we're here, assert accept, and a-im too; subtests, ideally

    # server responds with new caching headers
    server.set_response(
        data_dir.joinpath('empty.atom').read_text(),
        b'"11111-67890abcdef12"',
        b'Thu, 1 Jan 2020 11:11:11 GMT',
    )
    assert reader.update_feed(url).new == 0
    request_line, headers, body = server.request
    assert headers[b'If-None-Match'] == etag
    assert headers[b'If-Modified-Since'] == last_modified

    # assert new caching headers are used
    server.set_response(status_line='304 Not Modified')
    assert reader.update_feed(url) is None
    request_line, headers, body = server.request
    assert headers[b'If-None-Match'] == b'"11111-67890abcdef12"'
    assert headers[b'If-Modified-Since'] == b'Thu, 1 Jan 2020 11:11:11 GMT'
