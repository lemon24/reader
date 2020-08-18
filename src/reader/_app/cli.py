import click

import reader
from reader._cli import setup_logging
from reader._cli import split_defaults
from reader._config import merge_config


@click.command()
@click.pass_obj
@click.option('-h', '--host', default='localhost', help="The interface to bind to.")
@click.option('-p', '--port', default=8080, type=int, help="The port to bind to.")
@click.option(
    '--plugin',
    multiple=True,
    envvar=reader._APP_PLUGIN_ENVVAR,
    help="Import path to a plug-in. Can be passed multiple times.",
)
@click.option('-v', '--verbose', count=True)
def serve(config, host, port, plugin, verbose):
    """Start a local HTTP reader server."""
    setup_logging(verbose)
    from werkzeug.serving import run_simple
    from . import create_app

    default_options, user_options = split_defaults(
        {'plugins': {p: None for p in plugin}}
    )
    config['app'] = merge_config(default_options, config['app'], user_options)

    # FIXME: once create_app knows how to work from config, change these
    app = create_app(config)
    run_simple(host, port, app)
