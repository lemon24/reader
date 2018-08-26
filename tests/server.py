import http.server
import contextlib
import threading
import gzip
import ssl
import io


class GzipHandlerMixin:

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


class LastModifiedHandlerMixin:

    @property
    def last_modified(self):
        raise NotImplementedError

    def date_time_string(self, timestamp=None):
        return self.last_modified


class ErrorCodeHandlerMixin:

    @property
    def error_code(self):
        raise NotImplementedError

    def do_GET(self):
        self.send_error(self.error_code)


class RequestHeadersHandlerMixin:

    def send_response(self, *args, **kwargs):
        self.server.request_headers = self.headers
        return super().send_response(*args, **kwargs)


class ProtocolServerMixin:

    protocol = 'http'

    @property
    def url(self):
        return "{s.protocol}://{s.server_address[0]}:{s.server_address[1]}/".format(s=self)


class HTTPSServerMixin:

    protocol = 'https'

    def __init__(self, *args, **kwargs):
        certfile = kwargs.pop('certfile')
        super().__init__(*args, **kwargs)
        self.socket = ssl.wrap_socket(
            self.socket, certfile=certfile, server_side=True)


def make_httpd(server_address=('127.0.0.1', 0),
               gzip=False, last_modified=None, error_code=None,
               request_headers=False, certfile=None):

    if gzip and error_code:
        raise ValueError("gzip doesn't work with error_code")

    handler_bases = [http.server.SimpleHTTPRequestHandler]
    handler_attrs = {}
    server_bases = [ProtocolServerMixin, http.server.HTTPServer]
    server_kwargs = {}

    if gzip:
        handler_bases.insert(0, GzipHandlerMixin)
    if last_modified:
        handler_bases.insert(0, LastModifiedHandlerMixin)
        handler_attrs['last_modified'] = last_modified
    if error_code:
        handler_bases.insert(0, ErrorCodeHandlerMixin)
        handler_attrs['error_code'] = error_code
    if request_headers:
        handler_bases.insert(0, RequestHeadersHandlerMixin)
    if certfile:
        server_bases.insert(0, HTTPSServerMixin)
        server_kwargs['certfile'] = certfile

    Handler = type('Handler', tuple(handler_bases), handler_attrs)
    Server = type('Server', tuple(server_bases), {})

    return Server(server_address, Handler, **server_kwargs)


@contextlib.contextmanager
def run_httpd(**kwargs):
    httpd = make_httpd(**kwargs)
    threading.Thread(target=httpd.serve_forever).start()
    try:
        yield httpd
    finally:
        httpd.shutdown()



if __name__ == '__main__':  # pragma: no cover

    import subprocess

    # openssl req -new -x509 -keyout server.pem -out server.pem -days 365 -nodes

    kwargs = dict(gzip=True, last_modified='last-modified',
                  request_headers=True, certfile='server.pem')

    with run_httpd(**kwargs) as httpd:
        print("--- running at", httpd.url)

        out = subprocess.run(
            ['curl', '-k', '-s', '-D-', '-o/dev/null', httpd.url],
            stdout=subprocess.PIPE, universal_newlines=True,
        ).stdout
        print("--- curl output", out.strip(), sep='\n')

    headers = getattr(httpd, 'request_headers', None)
    if headers:
        print("--- headers", headers, sep='\n')

