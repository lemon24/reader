import functools
import inspect
import posixpath
from urllib.parse import urlparse


def make_url_base(feed_url):
    url_base = urlparse(feed_url)
    url_base = url_base._replace(
        path=posixpath.dirname(url_base.path), params='', query='', fragment=''
    ).geturl()
    if url_base:
        url_base = url_base.rstrip('/') + '/'

    rel_base = url_base if feed_url.startswith('http') else ''

    return url_base, rel_base


def rename_argument(original, alias):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            kwargs[original] = kwargs.pop(alias)
            return fn(**kwargs)

        signature = inspect.signature(fn)
        parameters = signature.parameters.copy()
        parameters[alias] = parameters.pop(original).replace(name=alias)
        signature = signature.replace(parameters=parameters.values())

        wrapper.__signature__ = signature

        return wrapper

    return decorator
