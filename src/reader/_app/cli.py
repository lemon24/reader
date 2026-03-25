import click

from reader._cli import setup_logging


def make_add_response_headers_middleware(wsgi_app, headers):
    def wsgi_app_wrapper(environ, start_response):
        def start_response_wrapper(status, response_headers, exc_info=None):
            response_headers.extend(headers)
            return start_response(status, response_headers, exc_info)

        return wsgi_app(environ, start_response_wrapper)

    return wsgi_app_wrapper


@click.group('web')
@click.option(
    '--plugin',
    'plugins',
    show_envvar=True,
    multiple=True,
    help="Import path to a web app plug-in. Can be passed multiple times.",
)
@click.option('--legacy/--no-legacy', help="Serve the legacy app.")
def cli(plugins, legacy):
    """Web application commands."""


@cli.command()
@click.option('-h', '--host', default='localhost', help="The interface to bind to.")
@click.option('-p', '--port', default=8080, type=int, help="The port to bind to.")
@click.option('-v', '--verbose', count=True)
@click.pass_context
def run(ctx, host, port, verbose):
    """Run a local HTTP reader server."""
    setup_logging(verbose)
    from werkzeug.serving import run_simple

    if not ctx.parent.params['legacy']:
        from . import create_app
    else:
        from .legacy import create_app

    app = create_app(ctx.find_root().params, ctx.parent.params['plugins'])

    app.wsgi_app = make_add_response_headers_middleware(
        app.wsgi_app,
        [('Referrer-Policy', 'same-origin')],
    )

    run_simple(host, port, app)
