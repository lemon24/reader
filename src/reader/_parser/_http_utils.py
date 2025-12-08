"""
HTTP utilities. Contains no business logic.

"""

from collections.abc import Iterable
from functools import partial

import werkzeug.http
from werkzeug.datastructures import MIMEAccept
from werkzeug.datastructures import ResponseCacheControl


parse_options_header = werkzeug.http.parse_options_header
parse_accept_header = werkzeug.http.parse_accept_header
parse_date = werkzeug.http.parse_date


def unparse_accept_header(values: Iterable[tuple[str, float]]) -> str:
    return MIMEAccept(values).to_header()


parse_cache_control_header = partial(
    werkzeug.http.parse_cache_control_header, cls=ResponseCacheControl
)
