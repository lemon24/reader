"""
Adding custom headers when retrieving feeds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Example of adding custom request headers with :attr:`.SessionFactory.request_hooks`:

.. code-block:: console

    $ python examples/custom_headers.py
    updating...
    server: Hello, world!
    updated!

"""

# fmt: off
# flake8: noqa

import http.server
import threading
from reader import make_reader

# start a background server that logs the received header

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        print("server:", self.headers.get('my-header'))
        self.send_error(304)

server = http.server.HTTPServer(('localhost', 8080), Handler)
threading.Thread(target=server.handle_request).start()

# create a reader object

reader = make_reader(':memory:')
reader.add_feed('http://localhost:8080')

# set up a hook that adds the header to each request

def hook(session, request, **kwargs):
    request.headers.setdefault('my-header', 'Hello, world!')

reader._parser.session_factory.request_hooks.append(hook)

# updating the feed sends the modified request to the server

print("updating...")
reader.update_feeds()
print("updated!")
