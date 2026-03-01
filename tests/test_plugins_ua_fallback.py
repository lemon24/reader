import pytest

from reader import ParseError


def test_fallback(requests_mock, make_reader):
    url = 'http://www.example.com/'

    reader = make_reader(':memory:', plugins=('reader.ua_fallback',))
    reader.add_feed(url)

    route = requests_mock.get(url, status_code=403)

    with pytest.raises(ParseError) as exc_info:
        reader.update_feed(url)

    assert '403' in str(exc_info.value)

    # respx uses route.calls instead of request_history
    assert len(route.calls) == 2
    first_ua = route.calls[0].request.headers['User-Agent']
    second_ua = route.calls[1].request.headers['User-Agent']

    assert first_ua.startswith('python-reader/')
    assert second_ua.startswith('feedparser/')
    assert second_ua.endswith(first_ua)


def test_noop(requests_mock, make_reader):
    url = 'http://www.example.com/'

    reader = make_reader(':memory:', plugins=('reader.ua_fallback',))
    reader.add_feed(url)

    route = requests_mock.get(url, status_code=404)

    with pytest.raises(ParseError) as exc_info:
        reader.update_feed(url)

    assert '404' in str(exc_info.value)
    # respx uses route.calls instead of request_history
    assert len(route.calls) == 1
