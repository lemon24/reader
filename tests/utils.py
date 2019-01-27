from urllib.parse import urlparse
import posixpath


def make_url_base(feed_url):
    url_base = urlparse(feed_url)
    url_base = url_base._replace(
        path=posixpath.dirname(url_base.path),
        params='', query='', fragment='',
    ).geturl()
    if url_base:
        url_base = url_base.rstrip('/') + '/'

    rel_base = url_base if feed_url.startswith('http') else ''

    return url_base, rel_base

