"""
Parsing a feed retrieved with something other than *reader*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Example of using the *reader* internal API to parse a feed
retrieved asynchronously with `HTTPX <https://www.python-httpx.org/>`_:

.. code-block:: console

    $ python examples/parser_only.py
    death and gravity
    Has your password been pwned? Or, how I almost failed to search a 37 GB text file in under 1 millisecond (in Python)

"""

import asyncio
import io
import httpx
from reader._parser import default_parser
from werkzeug.http import parse_options_header

url = "https://death.andgravity.com/_feed/index.xml"
meta_parser = default_parser()


async def main():
    async with httpx.AsyncClient() as client:
        response = await client.get(url)

        # to select the parser, we need the MIME type of the response
        content_type = response.headers.get('content-type')
        if content_type:
            mime_type, _ = parse_options_header(content_type)
        else:
            mime_type = None

        # select the parser (raises ParseError if none found)
        parser, _ = meta_parser.get_parser(url, mime_type)

        # wrap the content in a readable binary file
        file = io.BytesIO(response.content)

        # parse the feed; not doing parser(url, file, response.headers) directly
        # because parsing is CPU-intensive and would block the event loop
        feed, entries = await asyncio.to_thread(parser, url, file, response.headers)

        print(feed.title)
        print(entries[0].title)


if __name__ == '__main__':
    asyncio.run(main())
