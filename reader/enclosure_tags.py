import tempfile
from urllib.parse import urlparse

from flask import Blueprint, Response, stream_with_context, url_for, request


enclosure_tags_blueprint = Blueprint('enclosure_tags', __name__)


@enclosure_tags_blueprint.route('/enclosure-tags', defaults={'filename': None})
@enclosure_tags_blueprint.route('/enclosure-tags/<filename>')
def enclosure_tags(filename):
    import requests
    import mutagen.mp3

    def update_tags(file):
        emp3 = mutagen.mp3.EasyMP3(file)
        changed = False
        for key in ('album', 'title'):
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


def enclosure_tags_filter(enclosure, entry, feed):
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
        if feed.title:
            args['album'] = feed.title
        return url_for('enclosure_tags.enclosure_tags', **args)
    return enclosure.href


