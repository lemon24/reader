import click

from reader.cli import setup_logging


@click.command()
@click.pass_obj
@click.option('-h', '--host', default='localhost', show_default=True)
@click.option('-p', '--port', default=8080, show_default=True, type=int)
@click.option('-v', '--verbose', count=True)
def serve(db_path, host, port, verbose):
    setup_logging(verbose)
    from werkzeug.serving import run_simple
    from . import create_app
    app = create_app(db_path)
    run_simple(host, port, app)

