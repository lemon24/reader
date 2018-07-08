import tempfile
from urllib.parse import urlparse

from flask import Blueprint, Response, stream_with_context, url_for, request


enclosure_tags_blueprint = Blueprint('enclosure_tags', __name__)



ALL_TAGS = ('album', 'title', 'artist')
SET_ONLY_IF_MISSING_TAGS = {'artist'}


@enclosure_tags_blueprint.route('/enclosure-tags', defaults={'filename': None})
@enclosure_tags_blueprint.route('/enclosure-tags/<filename>')
def enclosure_tags(filename):
    import requests
    import mutagen.mp3

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
        for chunk in req.iter_content(chunk_size=None):
            tmp.write(chunk)
        tmp.seek(0)

        update_tags(tmp)

        try:
            while True:
                data = tmp.read(2**20)
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

    return Response(
        stream_with_context(chunks(req)),
        headers=headers,
    )


def enclosure_tags_filter(enclosure, entry):
    try:
        import mutagen
        import requests
    except ImportError:
        return enclosure.href
    filename = urlparse(enclosure.href).path.split('/')[-1]
    if filename.endswith('.mp3'):
        args = {'url': enclosure.href, 'filename': filename}
        if entry.title:
            args['title'] = entry.title
        if entry.feed.title:
            args['album'] = entry.feed.title
        if entry.author or entry.feed.author:
            args['artist'] = entry.author or entry.feed.author
        return url_for('enclosure_tags.enclosure_tags', **args)
    return enclosure.href


