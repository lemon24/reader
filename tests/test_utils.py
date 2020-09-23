import pickle

from reader._utils import FancyExceptionMixin


class MyException(FancyExceptionMixin, Exception):
    pass


def test_fancy_exception_mixin():
    exc = MyException('exception')
    assert str(exc) == 'exception'

    exc = MyException('exception', message='message')
    assert str(exc) == 'message: exception'

    cause = Exception('cause')

    exc = MyException('exception')
    exc.__cause__ = cause
    assert str(exc) == 'exception: builtins.Exception: cause'

    exc = MyException('exception', message='message')
    exc.__cause__ = cause
    pickled_exc = pickle.dumps(exc)
    assert str(exc) == 'message: exception: builtins.Exception: cause'
    assert str(exc) == str(pickle.loads(pickled_exc))

    class WithURL(MyException):
        message = 'default message'

        def __init__(self, url, **kwargs):
            super().__init__(**kwargs)
            self.url = url

        @property
        def _str(self):
            return self.url.upper()

    exc = WithURL('url')
    assert str(exc) == 'default message: URL'

    exc = WithURL('url', message='another message')
    exc.__cause__ = cause
    assert str(exc) == 'another message: URL: builtins.Exception: cause'
