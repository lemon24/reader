import click

import reader
from reader._cli import setup_logging


def make_add_response_headers_middleware(wsgi_app, headers):
    def wsgi_app_wrapper(environ, start_response):
        def start_response_wrapper(status, response_headers, exc_info=None):
            response_headers.extend(headers)
            return start_response(status, response_headers, exc_info)

        return wsgi_app(environ, start_response_wrapper)

    return wsgi_app_wrapper


@click.command()
@click.pass_obj
@click.option('-h', '--host', default='localhost', help="The interface to bind to.")
@click.option('-p', '--port', default=8080, type=int, help="The port to bind to.")
@click.option(
    '--plugin',
    multiple=True,
    envvar=reader._APP_PLUGIN_ENVVAR,
    help="Import path to a web app plug-in. Can be passed multiple times.",
)
@click.option('-v', '--verbose', count=True)
def serve(config, host, port, plugin, verbose):
    """Start a local HTTP reader server."""
    setup_logging(verbose)
    from werkzeug.serving import run_simple
    from . import create_app

    if plugin:
        config['app']['plugins'] = dict.fromkeys(plugin)

    # FIXME: remove this once we make debug_storage a storage_arg
    config['default']['reader'].pop('debug_storage', None)

    app = create_app(config)
    app.wsgi_app = make_add_response_headers_middleware(
        app.wsgi_app,
        [('Referrer-Policy', 'same-origin')],
    )

    run_simple(host, port, app)
