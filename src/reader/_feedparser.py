"""
feedparser 6.0 compatibility layer.

It can be deleted once feedparser 6.0 is released
and we bump our install_requires dependency to it.

"""
import threading
from typing import Any

import feedparser as fp  # type: ignore
from feedparser import CharacterEncodingOverride  # noqa: F401
from feedparser import NonXMLContentType  # noqa: F401

try:
    from feedparser import http
except ImportError:
    http = fp


def parse(*args: Any, **kwargs: Any) -> Any:
    try:
        return fp.parse(*args, **kwargs)
    except TypeError as e:
        if 'parse() got an unexpected keyword argument' not in str(
            e
        ):  # pragma: no cover
            raise

    # Best effort; still not safe if someone else changes the globals.
    with threading.Lock():
        old = fp.RESOLVE_RELATIVE_URIS, fp.SANITIZE_HTML
        fp.RESOLVE_RELATIVE_URIS, fp.SANITIZE_HTML = (
            kwargs.pop('resolve_relative_uris', fp.RESOLVE_RELATIVE_URIS),
            kwargs.pop('sanitize_html', fp.SANITIZE_HTML),
        )
        try:
            return fp.parse(*args, **kwargs)
        finally:
            fp.RESOLVE_RELATIVE_URIS, fp.SANITIZE_HTML = old
