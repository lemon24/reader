import pytest
import werkzeug.datastructures
import werkzeug.http

from reader._http_utils import parse_accept_header
from reader._http_utils import parse_options_header
from reader._http_utils import unparse_accept_header


@pytest.mark.parametrize(
    'value',
    [
        'one/two, one/*; q=0.1,three/four;q=0,three/*;q=0.2,type,another;q=x;type=1',
        'type;param=value,another;q=1;param=value',
        'type ;param=value, another; q=1 ;param=value',
        '',
        ',',
        ';',
        ',;',
        ';q=1',
        ';q=x',
        "type;q=10",
        "type;q=-10",
    ],
)
def test_parse_accept_header(value):
    assert parse_accept_header(value) == list(werkzeug.http.parse_accept_header(value))


@pytest.mark.parametrize(
    'values',
    [
        [('one', 1), ('one', 1), ('two', 0), ('three', 0.1), ('four', 0.1234)],
    ],
)
def test_unparse_accept_header(values):
    MA = werkzeug.datastructures.MIMEAccept
    assert unparse_accept_header(values) == MA(values).to_header()


@pytest.mark.parametrize(
    'value',
    [
        'one/two',
        'one/two;param=value',
        ' one/two ; param=value',
    ],
)
def test_parse_options_header(value):
    actual = parse_options_header(value)
    expected = werkzeug.http.parse_options_header(value)
    assert actual == expected
