import pathlib

import click
import platformdirs

from reader._cli import app_name
from reader._cli import load_reader_config_from_context
from reader._cli import setup_logging


def make_add_response_headers_middleware(wsgi_app, headers):
    def wsgi_app_wrapper(environ, start_response):
        def start_response_wrapper(status, response_headers, exc_info=None):
            response_headers.extend(headers)
            return start_response(status, response_headers, exc_info)

        return wsgi_app(environ, start_response_wrapper)

    return wsgi_app_wrapper


@click.command('web')
@click.option('-h', '--host', default='localhost', help="The interface to bind to.")
@click.option('-p', '--port', default=8080, type=int, help="The port to bind to.")
@click.option(
    '--plugin',
    'plugins',
    show_envvar=True,
    multiple=True,
    help="Import path to a web app plug-in. Can be passed multiple times.",
)
@click.option('--legacy/--no-legacy', help="Serve the legacy app.")
@click.option(
    '--cache-dir',
    type=click.Path(file_okay=False, path_type=pathlib.Path),
    default=platformdirs.user_cache_dir(app_name),
    show_default=True,
    help="The directory to store cache data in.",
)
@click.option('-v', '--verbose', count=True)
@click.pass_context
def cli(ctx, host, port, plugins, legacy, cache_dir, verbose):
    """Run a local HTTP reader server."""

    setup_logging(verbose)
    from werkzeug.serving import run_simple

    if not legacy:
        from . import create_app
    else:
        from .legacy import create_app

    app = create_app(load_reader_config_from_context())

    app.wsgi_app = make_add_response_headers_middleware(
        app.wsgi_app,
        [('Referrer-Policy', 'same-origin')],
    )

    run_simple(host, port, app)
