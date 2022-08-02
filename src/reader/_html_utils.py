"""
HTML utilities. Contains no business logic.

"""
import warnings
from typing import Optional

import bs4  # type: ignore


# BeautifulSoup warns if not giving it a parser explicitly; full text:
#
#   No parser was explicitly specified, so I'm using the best available
#   HTML parser for this system ("..."). This usually isn't a problem,
#   but if you run this code on another system, or in a different virtual
#   environment, it may use a different parser and behave differently.
#
# We are ok with any parser, and with how BeautifulSoup picks the best one if
# available. Explicitly using generic features (e.g. `('html', 'fast')`,
# the default) instead of a specific parser still warns.
#
# Currently there's no way to allow users to pick a parser, and we don't want
# to force a specific parser, so there's no point in warning.
#
# When changing this, also change the equivalent pytest.filterwarnings config.
#
# TODO: Expose BeautifulSoup(features=...) when we have a config system.
#
warnings.filterwarnings(
    'ignore', message='No parser was explicitly specified', module='reader._html_utils'
)


def strip_html(html: str, features: Optional[str] = None) -> str:
    soup = get_soup(html)
    remove_nontext_elements(soup)

    rv = soup.get_text(separator=' ')
    # TODO: Remove this assert once bs4 gets type annotations.
    assert isinstance(rv, str)

    return rv


def get_soup(html: str, features: Optional[str] = None) -> bs4.BeautifulSoup:
    return bs4.BeautifulSoup(html, features=features)


def remove_nontext_elements(soup: bs4.BeautifulSoup) -> None:
    # <script>, <noscript> and <style> don't contain things relevant to search.
    # <title> probably does, but its content should already be in the entry title.
    #
    # Although <head> is supposed to contain machine-readable content, Firefox
    # shows any free-floating text it contains, so we should keep it around.
    #
    for e in soup.select('script, noscript, style, title'):
        e.replace_with('\n')
