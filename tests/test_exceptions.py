import pickle

import pytest

from reader import EntryError
from reader import FeedError
from reader import SingleUpdateHookError
from reader import TagError
from reader import UpdateHookErrorGroup
from reader.exceptions import _FancyExceptionBase


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
        _default_message = 'default message'

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


def _all_classes(cls):
    yield cls
    for subclass in cls.__subclasses__():
        yield from _all_classes(subclass)


def all_classes(*args, **kwargs):
    return list(_all_classes(*args, **kwargs))


@pytest.mark.parametrize('exc_type', all_classes(FeedError))
def test_feed_error_str(exc_type):
    exc = exc_type('url')
    assert repr('url') in str(exc)


@pytest.mark.parametrize('exc_type', all_classes(EntryError))
def test_entry_error_str(exc_type):
    exc = exc_type('url', 'id')
    assert repr(('url', 'id')) in str(exc)


@pytest.mark.parametrize('exc_type', all_classes(TagError))
def test_tag_error_str(exc_type):
    exc = exc_type(('object',), 'key')
    assert "'object': 'key'" in str(exc)


@pytest.mark.parametrize(
    'args, expected',
    [
        (
            ('before_feeds_update', 'myhook'),
            "unexpected hook error: before_feeds_update: 'myhook'",
        ),
        (
            ('before_feeds_update', 'myhook', ()),
            "unexpected hook error: before_feeds_update: 'myhook': ()",
        ),
        (
            ('before_feed_update', 'myhook', ('feed',)),
            "unexpected hook error: before_feed_update: 'myhook': 'feed'",
        ),
        (
            ('after_entry_update', 'myhook', ('feed', 'entry')),
            "unexpected hook error: after_entry_update: 'myhook': ('feed', 'entry')",
        ),
    ],
)
def test_single_update_hook_error_str(args, expected):
    exc = SingleUpdateHookError(*args)
    assert str(exc) == expected
    exc = SingleUpdateHookError(*args)
    exc.__cause__ = Exception('cause')
    assert str(exc) == expected + ": builtins.Exception: cause"


def test_update_hook_error_group():
    one = SingleUpdateHookError('before_feeds_update', 'one')
    two = SingleUpdateHookError('before_feeds_update', 'two')

    group = UpdateHookErrorGroup('message', [one])
    assert group.message == 'message'
    assert group.exceptions == (one,)

    derived = group.derive([two])
    assert derived.message == 'message'
    assert derived.exceptions == (two,)

    with pytest.raises(TypeError):
        UpdateHookErrorGroup('message', [Exception()])
    with pytest.raises(TypeError):
        group.derive([Exception()])
