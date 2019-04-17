"""
tumblr_gdpr
~~~~~~~~~~~

Accept Tumblr GDPR  stuff.

Since May 2018, Tumblr redirects all new sessions to an "accept the terms of
service" page, including RSS feeds (supposed to be machine-readable),
breaking them.

This plugin "accepts the terms of service" on your behalf.

To load::

    READER_PLUGIN='reader.plugins.tumblr_gdpr:tumblr_gdpr' \\
    python -m reader update -v

Implemented for https://github.com/lemon24/reader/issues/67.

"""

import re


def make_headers(consent_form_url, tumblr_form_key):
    return {
        # anything starting with 'https://www.tumblr.com/' should work
        'Referer': consent_form_url,
        'X-tumblr-form-key': tumblr_form_key,
    }

def make_json_data():
    return {
        'eu_resident': True,
        'gdpr_consent_core': True,
        'gdpr_consent_first_party_ads': True,
        'gdpr_consent_search_history': True,
        'gdpr_consent_third_party_ads': True,
        'gdpr_is_acceptable_age': True,
    }

def extract_tumblr_form_key(text):
    match = re.search('<meta name="tumblr-form-key" id="tumblr_form_key" content="([^"]+)">', text)
    assert match
    return match.group(1)

def fill_cookie_jar_requests(session, consent_form_url):
    response = session.get(consent_form_url)
    assert response.status_code == 200

    tumblr_form_key = extract_tumblr_form_key(response.text)
    headers = make_headers(consent_form_url, tumblr_form_key)
    json_data = make_json_data()

    response = session.post('https://www.tumblr.com/svc/privacy/consent',
                            json=json_data, headers=headers)
    assert response.status_code == 200


def tumblr_gdpr_parse_response_plugin(session, response, request):
    if not response.url.startswith('https://www.tumblr.com/privacy/consent'):
        return None

    fill_cookie_jar_requests(session, response.url)
    return request


def tumblr_gdpr(reader):
    reader._parser.response_plugins.append(tumblr_gdpr_parse_response_plugin)


