"""
enclosure_tags
~~~~~~~~~~~~~~

Fix tags for MP3 enclosures (e.g. podcasts).

Adds a "with tags" link to a version of the file with tags set as follows:

* the entry title as title
* the feed title as album
* the entry/feed author as author

This plugin needs additional dependencies, use the ``unstable-plugins`` extra
to install them:

.. code-block:: bash

    pip install reader[unstable-plugins]

To load::

    READER_APP_PLUGIN='reader._plugins.enclosure_tags:init' \\
    python -m reader serve

Implemented for https://github.com/lemon24/reader/issues/50.
Became a plugin in https://github.com/lemon24/reader/issues/52.

"""
import tempfile
from urllib.parse import urlparse

import mutagen.mp3
import requests
from flask import Blueprint
from flask import request
from flask import Response
from flask import stream_with_context
from flask import url_for

blueprint = Blueprint('enclosure_tags', __name__)


ALL_TAGS = ('album', 'title', 'artist')
SET_ONLY_IF_MISSING_TAGS = {'artist'}


@blueprint.route('/enclosure-tags', defaults={'filename': None})
@blueprint.route('/enclosure-tags/<filename>')
def enclosure_tags(filename):
    def update_tags(file):
        emp3 = mutagen.mp3.EasyMP3(file)
        changed = False

        for key in ALL_TAGS:
            if key in SET_ONLY_IF_MISSING_TAGS and emp3.get(key):
                continue
            value = request.args.get(key)
            if not value:
                continue
            emp3[key] = [value]
            changed = True

        if changed:
            emp3.save(file)
        file.seek(0)

    def chunks(req):
        # Send the headers as soon as possible.
        # Some browsers wait for the headers before showing the "Save As" dialog.
        yield ''

        tmp = tempfile.TemporaryFile()
        for chunk in req.iter_content(chunk_size=2 ** 20):
            tmp.write(chunk)
        tmp.seek(0)

        update_tags(tmp)

        try:
            while True:
                data = tmp.read(2 ** 20)
                if not data:
                    break
                yield data
        finally:
            tmp.close()

    url = request.args['url']
    req = requests.get(url, stream=True)

    headers = {}
    for name in ('Content-Type', 'Content-Disposition'):
        if name in req.headers:
            headers[name] = req.headers[name]

    return Response(stream_with_context(chunks(req)), headers=headers)


def enclosure_tags_filter(enclosure, entry):
    filename = urlparse(enclosure.href).path.split('/')[-1]
    if not filename.endswith('.mp3'):
        return []

    args = {'url': enclosure.href, 'filename': filename}
    if entry.title:
        args['title'] = entry.title
    if entry.feed.title:
        args['album'] = entry.feed.title
    if entry.author or entry.feed.author:
        args['artist'] = entry.author or entry.feed.author

    return [('with tags', url_for('enclosure_tags.enclosure_tags', **args))]


def init(app):
    app.register_blueprint(blueprint)
    app.reader_additional_enclosure_links.append(enclosure_tags_filter)
