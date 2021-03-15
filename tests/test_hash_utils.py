from dataclasses import dataclass
from datetime import datetime

import pytest

from reader._hash_utils import check_hash
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


def three_factory(one, value):
    return DataTwo(one, three=value)


@pytest.mark.parametrize('value', ['', [], (), {}, None])
@pytest.mark.parametrize('factory', [DataOne, DataTwo, three_factory])
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
        (['list'], b'\x00\x1b\xd5\xf7N1\x0ee\xb3eSLvY\x1a['),
        (('tuple',), b'\x00P\x85\xa4n-\x82\x8b\xc4?\xf1\xdd\x10\xc7+R'),
        ({'key': 'value'}, b'\x00\x03\x91\xa5\x95P0\x0b&\x80\xe1\xd7!\x8b\x89m'),
        (DataOne(1, 2), b'\x00O\n\xc1\xe5A\x07\xf7\xe1[\x18X4\x84\x8a~'),
        (DataTwo(1, 2), b'\x00O\n\xc1\xe5A\x07\xf7\xe1[\x18X4\x84\x8a~'),
        (
            DataOne(1, DataTwo(2)),
            b'\x00\xc0\x9a/ \x946\x1cr\x9b\xca\xd4\xce\xc6\x02\xf0',
        ),
        (
            DataOne(1, [DataTwo(2), 3, datetime(2021, 1, 2)]),
            b"\x00\x8b\xbdL]kn\xb8\xec\xce\x81'\x9c\x06\r)",
        ),
        (
            DataOne(1, {'key': DataTwo(datetime(2021, 1, 2))}),
            b'\x005\xda2\xd3(r\x99\xd3\xa3\x10z\x1c-u\xfc',
        ),
    ],
)
def test_hash(thing, hash):
    assert check_hash(thing, hash) is True
    assert check_hash(thing, bytes(16)) is False
    # for version 0 this is true
    assert get_hash(thing) == hash


@pytest.mark.parametrize('thing', [object(), str, {1, 2}, b'ab'])
def test_hash_error(thing):
    with pytest.raises(TypeError):
        get_hash(DataOne(thing))
