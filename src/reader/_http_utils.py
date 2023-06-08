"""
HTTP utilities. Contains no business logic.

Vendored from werkzeug (we don't want to depend on it).

Last updated to werkzeug 2.3.2.

"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import unquote

__all__ = ['parse_accept_header', 'parse_options_header', 'unparse_accept_header']


def parse_accept_header(value: str) -> list[tuple[str, float]]:  # pragma: no cover
    """werkzeug.http.parse_accept_header(), but returns a plain list."""
    if not value:
        return []

    result = []

    for item in parse_list_header(value):
        item, options = parse_options_header(item)

        if "q" in options:
            try:
                # pop q, remaining options are reconstructed
                q = _plain_float(options.pop("q"))
            except ValueError:
                # ignore an invalid q
                continue

            if q < 0 or q > 1:
                # ignore an invalid q
                continue
        else:
            q = 1

        if options:
            # reconstruct the media type with any options
            item = dump_options_header(item, options)

        result.append((item, q))

    result.sort(key=lambda t: t[1], reverse=True)

    return result


def parse_list_header(value: str) -> list[str]:  # pragma: no cover
    result = []

    for item in _parse_list_header(value):
        if len(item) >= 2 and item[0] == item[-1] == '"':
            item = item[1:-1]

        result.append(item)

    return result


def _parse_list_header(s: str) -> list[str]:  # pragma: no cover
    """urllib.request.parse_http_list().

    Vendored because urllib.request is slow to import;
    https://github.com/lemon24/reader/issues/297

    """
    res = []
    part = ''

    escape = quote = False
    for cur in s:
        if escape:
            part += cur
            escape = False
            continue
        if quote:
            if cur == '\\':
                escape = True
                continue
            elif cur == '"':
                quote = False
            part += cur
            continue

        if cur == ',':
            res.append(part)
            part = ''
            continue

        if cur == '"':
            quote = True

        part += cur

    # append last part
    if part:
        res.append(part)

    return [part.strip() for part in res]


def dump_options_header(
    header: str | None, options: dict[str, Any]
) -> str:  # pragma: no cover
    segments = []

    if header is not None:
        segments.append(header)

    for key, value in options.items():
        if value is None:
            continue

        if key[-1] == "*":
            segments.append(f"{key}={value}")
        else:
            segments.append(f"{key}={quote_header_value(value)}")

    return "; ".join(segments)


_token_chars = frozenset(
    "!#$%&'*+-.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ^_`abcdefghijklmnopqrstuvwxyz|~"
)


def quote_header_value(value: str) -> str:  # pragma: no cover
    """werkzeug.http.quote_header_value(), but without options."""

    if not value:
        return '""'

    if _token_chars.issuperset(value):
        return value

    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


# https://httpwg.org/specs/rfc9110.html#parameter
_parameter_re = re.compile(
    r"""
    # don't match multiple empty parts, that causes backtracking
    \s*;\s*  # find the part delimiter
    (?:
        ([\w!#$%&'*+\-.^`|~]+)  # key, one or more token chars
        =  # equals, with no space on either side
        (  # value, token or quoted string
            [\w!#$%&'*+\-.^`|~]+  # one or more token chars
        |
            "(?:\\\\|\\"|.)*?"  # quoted string, consuming slash escapes
        )
    )?  # optionally match key=value, to account for empty parts
    """,
    re.ASCII | re.VERBOSE,
)
# https://www.rfc-editor.org/rfc/rfc2231#section-4
_charset_value_re = re.compile(
    r"""
    ([\w!#$%&*+\-.^`|~]*)'  # charset part, could be empty
    [\w!#$%&*+\-.^`|~]*'  # don't care about language part, usually empty
    ([\w!#$%&'*+\-.^`|~]+)  # one or more token chars with percent encoding
    """,
    re.ASCII | re.VERBOSE,
)
# https://www.rfc-editor.org/rfc/rfc2231#section-3
_continuation_re = re.compile(r"\*(\d+)$", re.ASCII)


def parse_options_header(value: str) -> tuple[str, dict[str, str]]:  # pragma: no cover
    """werkzeug.http.parse_options_header()."""

    value, _, rest = value.partition(";")
    value = value.strip()
    rest = rest.strip()

    if not value or not rest:
        # empty (invalid) value, or value without options
        return value, {}

    rest = f";{rest}"
    options: dict[str, str] = {}
    encoding: str | None = None
    continued_encoding: str | None = None

    for pk, pv in _parameter_re.findall(rest):
        if not pk:
            # empty or invalid part
            continue

        pk = pk.lower()

        if pk[-1] == "*":
            # key*=charset''value becomes key=value, where value is percent encoded
            pk = pk[:-1]
            match = _charset_value_re.match(pv)

            if match:
                # If there is a valid charset marker in the value, split it off.
                encoding, pv = match.groups()
                # This might be the empty string, handled next.
                encoding = encoding.lower()

            # No charset marker, or marker with empty charset value.
            if not encoding:
                encoding = continued_encoding

            # A safe list of encodings. Modern clients should only send ASCII or UTF-8.
            # This list will not be extended further. An invalid encoding will leave the
            # value quoted.
            if encoding in {"ascii", "us-ascii", "utf-8", "iso-8859-1"}:
                # Continuation parts don't require their own charset marker. This is
                # looser than the RFC, it will persist across different keys and allows
                # changing the charset during a continuation. But this implementation is
                # much simpler than tracking the full state.
                continued_encoding = encoding
                # invalid bytes are replaced during unquoting
                pv = unquote(pv, encoding=encoding)

        # Remove quotes. At this point the value cannot be empty or a single quote.
        if pv[0] == pv[-1] == '"':
            # HTTP headers use slash, multipart form data uses percent
            pv = pv[1:-1].replace("\\\\", "\\").replace('\\"', '"').replace("%22", '"')

        match = _continuation_re.search(pk)

        if match:
            # key*0=a; key*1=b becomes key=ab
            pk = pk[: match.start()]
            options[pk] = options.get(pk, "") + pv
        else:
            options[pk] = pv

    return value, options


def unparse_accept_header(values: Iterable[tuple[str, float]]) -> str:
    """werkzeug.datastructures.MIMEAccept(values).to_header()."""
    values = sorted(values, key=lambda t: t[1], reverse=True)

    result = []
    for value, quality in values:
        if quality != 1:
            value = f"{value};q={quality}"
        result.append(value)
    return ",".join(result)


_plain_float_re = re.compile(r"-?\d+\.\d+", re.ASCII)


def _plain_float(value: str) -> float:
    """werkzeug._internal._plain_float"""
    if _plain_float_re.fullmatch(value) is None:
        raise ValueError

    return float(value)
