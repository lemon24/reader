"""
HTTP utilities. Contains no business logic.

This mainly exists because we didn't want to depend on werkzeug.

"""
import re
from typing import Dict
from typing import Iterable
from typing import List
from typing import Tuple


# copied from werkzeug.http
_accept_re = re.compile(
    r"""
    (                       # media-range capturing-parenthesis
      [^\s;,]+              # type/subtype
      (?:[ \t]*;[ \t]*      # ";"
        (?:                 # parameter non-capturing-parenthesis
          [^\s;,q][^\s;,]*  # token that doesn't start with "q"
        |                   # or
          q[^\s;,=][^\s;,]* # token that is more than just "q"
        )
      )*                    # zero or more parameters
    )                       # end of media-range
    (?:[ \t]*;[ \t]*q=      # weight is a "q" parameter
      (\d*(?:\.\d+)?)       # qvalue capturing-parentheses
      [^,]*                 # "extension" accept params: who cares?
    )?                      # accept params are optional
    """,
    re.VERBOSE,
)


def parse_accept_header(value: str) -> List[Tuple[str, float]]:
    """Like werkzeug.http.parse_accept_header(), but returns a plain list."""
    # copied from werkzeug.http, with some modifications

    if not value:
        return []

    result = []
    for match in _accept_re.finditer(value):
        quality_match = match.group(2)
        if not quality_match:
            quality: float = 1
        else:
            quality = max(min(float(quality_match), 1), 0)
        result.append((match.group(1), quality))

    result.sort(key=lambda t: t[1], reverse=True)

    return result


def unparse_accept_header(values: Iterable[Tuple[str, float]]) -> str:
    """Like werkzeug.datastructures.MIMEAccept(values).to_header()."""
    parts = []
    for value, quality in sorted(values, key=lambda t: t[1], reverse=True):
        if quality != 1:
            value = f"{value};q={quality}"
        parts.append(value)
    return ','.join(parts)


def parse_options_header(value: str) -> Tuple[str, Dict[str, str]]:
    """Like werkzeug.http.parse_options_header(), but ignores the options."""
    return value.partition(';')[0].strip(), {}
