import click

from reader.cli import setup_logging


@click.command()
@click.pass_obj
@click.option('-h', '--host', default='localhost',
    help="The interface to bind to.")
@click.option('-p', '--port', default=8080, type=int,
    help="The port to bind to.")
@click.option('-v', '--verbose', count=True)
def serve(kwargs, host, port, verbose):
    """Start a local HTTP reader server.

    """
    setup_logging(verbose)
    from werkzeug.serving import run_simple
    from . import create_app
    app = create_app(kwargs['db_path'], kwargs['plugins'])
    run_simple(host, port, app)

