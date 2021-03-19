from dataclasses import dataclass
from datetime import datetime

import pytest

from reader._hash_utils import get_hash


@dataclass
class DataOne:
    one: object
    two: object = None


@dataclass
class DataTwo:
    one: object
    two: object = None
    three: object = None


def two_factory(one, value):
    return DataTwo(one, three=value)


@dataclass
class DataThree:
    one: object
    two: object = None
    _hash_exclude_ = frozenset(
        {
            'one',
        }
    )


@pytest.mark.parametrize('value', ['', [], (), {}, None])
@pytest.mark.parametrize('factory', [DataOne, DataTwo, two_factory])
def test_empty(value, factory):
    assert get_hash(DataOne(1)) == get_hash(factory(1, value))
    assert get_hash(DataOne(1, factory(2, value))) == get_hash(
        DataOne(1, factory(2, value))
    )


@pytest.mark.parametrize(
    'thing, hash',
    [
        (None, b'\x007\xa6%\x9c\xc0\xc1\xda\xe2\x99\xa7\x86d\x89\xdf\xf0'),
        (True, b'\x00\xb3&\xb5\x06+/\x0ei\x04h\x10qu4\xcb'),
        (1, b'\x00\xc4\xcaB8\xa0\xb9#\x82\r\xccP\x9aou\x84'),
        ('str', b'\x00v~-y\x12\xeb\xef\xdf\xe1\x84\x95\xedSc_'),
        (['list'], b'\x00\xe1y\x01T;\x817\x06\x03\xeb\x03\x07\xf4\xed\xc5'),
        (('tuple',), b'\x00\x95\xab\xbex\xc6\xff@\xdd\x02\xd5N\\\\\xbbY'),
        ({'key': 'value'}, b"\x00\xa75?|\xdd\xce\x80\x8d\xe0\x03'G\xa0\xb7\xbe"),
        (DataOne(1, 2), b'\x00\xbd]\x03\xe5\x0c\xca\xc3\xae\x17\xf1\x84\x01R@c'),
        (DataTwo(1, 2), b'\x00\xbd]\x03\xe5\x0c\xca\xc3\xae\x17\xf1\x84\x01R@c'),
        (DataOne(1, DataTwo(2)), b'\x00\xc4[\xfcY0\xffJ--\xb6\xd1M\xd7(\x8f'),
        (
            DataOne(1, [DataTwo(2), 3, datetime(2021, 1, 2)]),
            b'\x00uU\xb7\xf7\x18\xfa\x06\x98h\x82\xeb\xfd\xdc\xbd.',
        ),
        (
            DataOne(1, {'key': DataTwo(datetime(2021, 1, 2))}),
            b'\x00\xc82CV\xed\xff.\x8d\x9e5&\xbc\xd4e/',
        ),
    ],
)
def test_hash(thing, hash):
    assert get_hash(thing) == hash


@pytest.mark.parametrize('thing', [object(), str, {1, 2}, b'ab'])
def test_hash_error(thing):
    with pytest.raises(TypeError):
        get_hash(DataOne(thing))
    with pytest.raises(TypeError):
        get_hash(DataOne)


def test_exclude():
    assert get_hash(DataTwo(None, 2)) == get_hash(DataThree(1, 2))
    assert get_hash(DataTwo(1, 2)) != get_hash(DataThree(1, 2))
    assert get_hash(DataOne(DataTwo(None, 2), 'one')) == get_hash(
        DataOne(DataThree(1, 2), 'one')
    )
