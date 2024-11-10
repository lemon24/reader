"""
HTTP utilities. Contains no business logic.

"""

from collections.abc import Iterable

import werkzeug.http


parse_options_header = werkzeug.http.parse_options_header
parse_accept_header = werkzeug.http.parse_accept_header
parse_date = werkzeug.http.parse_date


def unparse_accept_header(values: Iterable[tuple[str, float]]) -> str:
    return werkzeug.datastructures.MIMEAccept(values).to_header()
