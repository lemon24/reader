import pytest

from reader._utils import deprecated_wrapper

# Normally, the stuff in _utils is tested by tests for higher level code,
# but some of the things aren't always used.


def test_deprecated_wrapper():
    def func(arg):
        raise ValueError(arg)

    old_func = deprecated_wrapper('old_func', func, '1.0', '2.0')

    with pytest.raises(ValueError) as excinfo, pytest.deprecated_call() as warnings:
        old_func('whatever')

    assert excinfo.value.args[0] == 'whatever'

    assert old_func.__name__ == 'old_func'
    assert old_func.__doc__ == (
        'Deprecated alias for :meth:`func`.\n\n'
        '.. deprecated:: 1.0\n'
        '    This method will be removed in *reader* 2.0.\n'
        '    Use :meth:`func` instead.\n\n'
    )

    assert len(warnings.list) == 1
    warning = warnings.pop()

    assert warning.category is DeprecationWarning
    assert (
        str(warning.message)
        == 'old_func() is deprecated and will be removed in reader 2.0. Use func() instead.'
    )
