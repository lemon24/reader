import warnings

import pytest

import reader._feedparser


def test_feedparser_5_warning(monkeypatch, recwarn):
    monkeypatch.setattr('feedparser.__version__', '5.2.1')
    with pytest.deprecated_call():
        reader._feedparser.parse('string')

    recwarn.clear()
    warnings.simplefilter("always")
    monkeypatch.setattr('feedparser.__version__', '6.0.1')
    reader._feedparser.parse('string')
    assert not recwarn.list
