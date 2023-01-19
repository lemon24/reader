import socketserver
import threading

import pytest


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


@pytest.mark.slow
def test_etag_last_modified(reader, data_dir, server):
    """Check ETag / Last-Modified are sent back, at the wire level.

    Because of https://rachelbythebay.com/w/2023/01/18/http/

    """
    etag = b'"12345-67890abcdef12"'
    last_modified = b'Thu, 1 Jan 2020 00:00:00 GMT'

    server.set_response(data_dir.join('full.atom').read(), etag, last_modified)
    url = server.url

    reader.add_feed(url)

    assert reader.update_feed(url).new == 2
    request_line, headers, body = server.request
    assert request_line == b'GET / HTTP/1.1'
    assert body == b''
    assert b'If-None-Match' not in headers
    assert b'If-Modified-Since' not in headers

    server.set_response(status_line='304 Not Modified')
    assert reader.update_feed(url) is None
    request_line, headers, body = server.request
    assert request_line == b'GET / HTTP/1.1'
    assert body == b''
    assert headers[b'If-None-Match'] == etag
    assert headers[b'If-Modified-Since'] == last_modified

    # TODO: since we're here, assert user agent, accept, and a-im too
