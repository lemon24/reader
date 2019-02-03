from collections import OrderedDict

import pytest
import attr

from reader.core.types import attrs_namedtuple_compat


def test_attrs_namedtuple_compat():

    @attr.s(slots=True, frozen=True)
    class Object(attrs_namedtuple_compat):
        one = attr.ib()
        two = attr.ib(default=None)

    assert Object._make((1, 2)) == Object(1, 2)
    with pytest.raises(TypeError):
        Object._make((1, ))
    with pytest.raises(TypeError):
        Object._make((1, 2, 3))

    assert Object(1, 1)._replace(two=2) == Object(1, 2)

    assert Object(1, 2)._asdict() == OrderedDict([['one', 1], ['two', 2]])


