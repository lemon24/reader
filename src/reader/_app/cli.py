import click

import reader
from reader._cli import setup_logging


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
    run_simple(host, port, app)
