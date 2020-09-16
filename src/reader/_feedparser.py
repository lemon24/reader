"""
feedparser 6.0 compatibility layer.

It can be deleted once feedparser 6.0 is released
and we bump our install_requires dependency to it.

"""
import threading
import warnings
from typing import Any

import feedparser as fp  # type: ignore
from feedparser import CharacterEncodingOverride  # noqa: F401
from feedparser import NonXMLContentType  # noqa: F401

try:
    from feedparser import http
except ImportError:
    http = fp


class _ReadWrapper:
    def __init__(self, file: Any):
        self._file = file

    def read(self, *args: Any) -> Any:
        return self._file.read(*args)


def parse(thing: Any, **kwargs: Any) -> Any:
    fp_major_version = int(fp.__version__.partition('.')[0])
    if fp_major_version < 6:
        warnings.warn(
            "feedparser 5.* reader support is deprecated, "
            "and will be removed in reader 1.8. "
            "Use the newer feedparser 6.* instead.",
            DeprecationWarning,
        )

    # feedparser 6.0 doesn't decode the content.
    # feedparser 5.* looks at thing.headers['content-encoding'].
    if hasattr(thing, 'read'):
        thing = _ReadWrapper(thing)

    try:
        return fp.parse(thing, **kwargs)
    except TypeError as e:
        unexpected_kw = 'parse() got' in str(e) and 'unexpected keyword' in str(e)
        if not unexpected_kw:  # pragma: no cover
            raise

    # Best effort; still not safe if someone else changes the globals.
    with threading.Lock():
        old = fp.RESOLVE_RELATIVE_URIS, fp.SANITIZE_HTML
        fp.RESOLVE_RELATIVE_URIS, fp.SANITIZE_HTML = (
            kwargs.pop('resolve_relative_uris', fp.RESOLVE_RELATIVE_URIS),
            kwargs.pop('sanitize_html', fp.SANITIZE_HTML),
        )
        try:
            return fp.parse(thing, **kwargs)
        finally:
            fp.RESOLVE_RELATIVE_URIS, fp.SANITIZE_HTML = old
