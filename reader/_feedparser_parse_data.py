import urllib.parse
import xml.sax


try:
    # for the GitHub version
    # https://github.com/kurtmckee/feedparser/tree/5646f4ca2069ffea349618eef9566005afec665e
    from feedparser.api import (
        convert_to_utf8,
        StrictFeedParser,
        LooseFeedParser,
        replace_doctype, _makeSafeAbsoluteURI,
        _XML_AVAILABLE, _SGML_AVAILABLE, PREFERRED_XML_PARSERS,
        _StringIO,
        bytes_,
    )
except ImportError:
    # for the '5.2.1' in Ubuntu 16.04 / 18.04
    from feedparser import (
        convert_to_utf8 as original_convert_to_utf8,
        _StrictFeedParser as StrictFeedParser,
        _LooseFeedParser as LooseFeedParser,
        replace_doctype, _makeSafeAbsoluteURI,
        _XML_AVAILABLE, _SGML_AVAILABLE, PREFERRED_XML_PARSERS,
        _StringIO,
    )

    def convert_to_utf8(http_headers, data, result):
        data, rfc3023_encoding, error = original_convert_to_utf8(http_headers, data)
        result['encoding'] = rfc3023_encoding
        if error:
            result['bozo'] = 1
            result['bozo_exception'] = error
        return data

    bytes_ = bytes


def _feedparser_parse_snippet(result, data, resolve_relative_uris=True, sanitize_html=True):
    """This is a verbatim snippet from feedparser.api.parse().

    https://github.com/kurtmckee/feedparser/blob/5646f4ca2069ffea349618eef9566005afec665e/feedparser/api.py#L168

    """

    # BEGIN "feedparser.api.parse()"

    data = convert_to_utf8(result['headers'], data, result)
    use_strict_parser = result['encoding'] and True or False

    result['version'], data, entities = replace_doctype(data)

    # Ensure that baseuri is an absolute URI using an acceptable URI scheme.
    contentloc = result['headers'].get('content-location', '')
    href = result.get('href', '')
    baseuri = _makeSafeAbsoluteURI(href, contentloc) or _makeSafeAbsoluteURI(contentloc) or href

    baselang = result['headers'].get('content-language', None)
    if isinstance(baselang, bytes_) and baselang is not None:
        baselang = baselang.decode('utf-8', 'ignore')

    if not _XML_AVAILABLE:
        use_strict_parser = 0
    if use_strict_parser:
        # initialize the SAX parser
        feedparser = StrictFeedParser(baseuri, baselang, 'utf-8')
        feedparser.resolve_relative_uris = resolve_relative_uris
        feedparser.sanitize_html = sanitize_html
        saxparser = xml.sax.make_parser(PREFERRED_XML_PARSERS)
        saxparser.setFeature(xml.sax.handler.feature_namespaces, 1)
        try:
            # disable downloading external doctype references, if possible
            saxparser.setFeature(xml.sax.handler.feature_external_ges, 0)
        except xml.sax.SAXNotSupportedException:
            pass
        saxparser.setContentHandler(feedparser)
        saxparser.setErrorHandler(feedparser)
        source = xml.sax.xmlreader.InputSource()
        source.setByteStream(_StringIO(data))
        try:
            saxparser.parse(source)
        except xml.sax.SAXException as e:
            result['bozo'] = 1
            result['bozo_exception'] = feedparser.exc or e
            use_strict_parser = 0
    if not use_strict_parser and _SGML_AVAILABLE:
        feedparser = LooseFeedParser(baseuri, baselang, 'utf-8', entities)
        feedparser.resolve_relative_uris = resolve_relative_uris
        feedparser.sanitize_html = sanitize_html
        feedparser.feed(data.decode('utf-8', 'replace'))
    result['feed'] = feedparser.feeddata
    result['entries'] = feedparser.entries
    result['version'] = result['version'] or feedparser.version
    result['namespaces'] = feedparser.namespacesInUse

    # END "feedparser.api.parse()"

