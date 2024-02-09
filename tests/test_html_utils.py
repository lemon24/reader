import bs4
import pytest

from reader._storage._html_utils import strip_html


STRIP_HTML_DATA = [
    ('', ''),
    ('<br>', ''),
    ('aabb', 'aabb'),
    ('aa<br>bb', 'aa\nbb'),
    ('aa<p>bb', 'aa\nbb'),
    ('<script>ss</script>bb', 'bb'),
    ('<noscript>ss</noscript>bb', 'bb'),
    ('<style>ss</style>bb', 'bb'),
    ('<title>ss</title>bb', 'bb'),
    ('aa<script>ss</script>bb', 'aa\nbb'),
    ('aa<noscript>ss</noscript>bb', 'aa\nbb'),
    ('aa<style>ss</style>bb', 'aa\nbb'),
    ('aa<title>tt</title>bb', 'aa\nbb'),
    ('<head><script>ss</script></head>bb', 'bb'),
    ('<head><noscript>ss</noscript>bb', 'bb'),
    ('<head><style>ss</style></head>bb', 'bb'),
    ('<head><title>tt</title>bb', 'bb'),
    ('<head>aa<script>ss</script>bb', 'aa\nbb'),
    ('<head>aa<noscript>ss</noscript></head>bb', 'aa\nbb'),
    ('<head>aa<style>ss</style>bb', 'aa\nbb'),
    ('<head>aa<title>tt</title></head>bb', 'aa\nbb'),
    (
        """
        <head>
            aa
            <title>tt</title>
            <p>bb
            <script>ss</script>
            <b>cc
            <noscript>nn</noscript>
            <style>ss</style>
            dd
        </head>
        ee
        """,
        'aa\nbb\ncc\ndd\nee',
    ),
]


# We test all bs4 parsers, since we don't know/care what the user has installed.
@pytest.mark.parametrize(
    'features',
    [
        None,
        pytest.param('lxml', marks=pytest.mark.requires_lxml),
        'html.parser',
        'html5lib',
    ],
)
@pytest.mark.parametrize('input, expected_output', STRIP_HTML_DATA)
def test_strip_html(input, expected_output, features):
    output = strip_html(input, features)
    if isinstance(output, str):
        output = '\n'.join(output.split())

    # Special-case different <noscript> handling by html.parser/html5lib.
    # https://www.crummy.com/software/BeautifulSoup/bs4/doc/#differences-between-parsers
    default_builder_is_lxml = 'lxml' in type(bs4.BeautifulSoup('').builder).__module__
    bad_at_noscript = features in {'html.parser', 'html5lib'} or (
        features is None and not default_builder_is_lxml
    )
    if bad_at_noscript and '<noscript>' in input:
        assert '<noscript>' not in output
        return

    assert output == expected_output
