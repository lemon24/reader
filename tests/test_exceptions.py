import pickle

import pytest

from reader.exceptions import _FancyExceptionBase
from reader.exceptions import EntryError
from reader.exceptions import FeedError
from reader.exceptions import MetadataError


def test_fancy_exception_base():
    exc = _FancyExceptionBase('message')
    assert str(exc) == 'message'

    exc = _FancyExceptionBase(message='message')
    assert str(exc) == 'message'

    cause = Exception('cause')

    exc = _FancyExceptionBase('message')
    exc.__cause__ = cause
    pickled_exc = pickle.dumps(exc)
    assert str(exc) == 'message: builtins.Exception: cause'
    assert str(exc) == str(pickle.loads(pickled_exc))

    class WithURL(_FancyExceptionBase):
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


@pytest.mark.parametrize('exc_type', [FeedError] + FeedError.__subclasses__())
def test_feed_error_str(exc_type):
    exc = exc_type('url')
    assert repr('url') in str(exc)


@pytest.mark.parametrize('exc_type', [EntryError] + EntryError.__subclasses__())
def test_entry_error_str(exc_type):
    exc = exc_type('url', 'id')
    assert repr(('url', 'id')) in str(exc)


@pytest.mark.parametrize('exc_type', [MetadataError] + MetadataError.__subclasses__())
def test_metadata_error_str(exc_type):
    exc = exc_type('url', 'key')
    assert (repr('url') + ': ' + repr('key')) in str(exc)
