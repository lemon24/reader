import pytest

from reader._utils import deprecated
from reader._utils import deprecated_wrapper


# Normally, the stuff in _utils is tested by tests for higher level code,
# but some of the things aren't always used.


def test_deprecated_wrapper():
    def new(arg):
        raise ValueError(arg)

    old = deprecated_wrapper('old', new, '1.0', '2.0')

    _check_deprecated(old)


def test_deprecated():
    @deprecated('new', '1.0', '2.0')
    def old(arg):
        "docstring"
        raise ValueError(arg)

    assert '\n\ndocstring\n\n' in old.__doc__

    _check_deprecated(old)


def test_deprecated_property():
    class Class:
        @property
        @deprecated('new', '1.0', '2.0', property=True)
        def old(self):
            "docstring"
            raise ValueError()

    with pytest.raises(ValueError), pytest.deprecated_call() as warnings:
        Class().old

    assert Class.old.fget.__name__ == 'old'
    assert Class.old.fget.__doc__ == (
        'Deprecated variant of :attr:`new`.\n\n'
        'docstring\n'
        '\n'
        '.. deprecated:: 1.0\n'
        '    This property will be removed in *reader* 2.0.\n'
        '    Use :attr:`new` instead.\n\n'
    )

    warning = warnings.pop()

    assert (
        str(warning.message)
        == 'old is deprecated and will be removed in reader 2.0. Use new instead.'
    )


def _check_deprecated(old):
    with pytest.raises(ValueError) as excinfo, pytest.deprecated_call() as warnings:
        old('whatever')

    assert excinfo.value.args[0] == 'whatever'

    assert old.__name__ == 'old'
    assert old.__doc__.startswith('Deprecated alias for :meth:`new`.\n\n')
    assert old.__doc__.endswith(
        '\n'
        '.. deprecated:: 1.0\n'
        '    This method will be removed in *reader* 2.0.\n'
        '    Use :meth:`new` instead.\n\n'
    )

    assert len(warnings.list) == 1
    warning = warnings.pop()

    assert warning.category is DeprecationWarning
    assert (
        str(warning.message)
        == 'old() is deprecated and will be removed in reader 2.0. Use new() instead.'
    )


def test_better_str_partial():
    from reader._utils import BetterStrPartial as partial

    def fn():
        pass

    assert str(partial(fn, 1, two=2)) == "fn(1, two=2)"

    fn.__name__ = ''
    assert str(partial(fn, 1)) == "<noname>(1)"

    class Cls:
        def meth(self):
            pass

    assert str(partial(Cls.meth, two=2)) == 'meth(two=2)'
    assert str(partial(Cls().meth, two=2)) == 'meth(two=2)'
