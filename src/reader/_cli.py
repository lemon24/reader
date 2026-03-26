import functools
import logging
import os.path
import shutil
import sys
from contextlib import nullcontext
from datetime import datetime

import click

import reader

from . import make_reader
from . import StorageError
from ._config_utils import config_option
from ._config_utils import extend_defaults
from ._config_utils import extract_args
from ._config_utils import load_config
from ._config_utils import load_config_from_context
from .plugins._loader import PluginLoader


app_name = reader.__name__
app_dir = click.get_app_dir(app_name)


log = logging.getLogger(__name__)


def load_reader_config(*args):
    config = load_config(cli, args)
    config[''] = extract_args(config[''], make_reader)
    return config


def load_reader_config_from_context():
    config = load_config_from_context()
    config[''] = extract_args(config[''], make_reader)
    return config


def abort(message, *args, **kwargs):
    raise click.ClickException(message.format(*args, **kwargs))


def setup_logging(verbose):
    if verbose < 0:
        return
    if verbose == 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG
    logging.getLogger('reader').setLevel(level)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s %(process)7s %(levelname)-8s %(message)s', '%Y-%m-%dT%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logging.getLogger('reader').addHandler(handler)


def make_log_verbose(expose_value=False, initial=0):
    def log_verbose(fn):
        @click.option('-v', '--verbose', count=True)
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            setup_logging(kwargs['verbose'] + initial)
            if not expose_value:
                del kwargs['verbose']
            return fn(*args, **kwargs)

        return wrapper

    return log_verbose


log_verbose = make_log_verbose()


def log_command(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context()
        params = []
        while ctx:
            params.append((ctx.info_name, ctx.params))
            ctx = ctx.parent

        log.info(
            "command started: %s", ' '.join(f"{n} {p}" for n, p in reversed(params))
        )

        try:
            rv = fn(*args, **kwargs)
            log.info("command finished successfully")
            return rv
        except Exception as e:
            log.critical(
                "command failed due to unexpected error: %s; traceback follows",
                e,
                exc_info=True,
            )
            # always raise, even if it's ReaderError (it could be due to a bug)
            raise

    return wrapper


def pass_reader(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        reader_args = load_reader_config_from_context()['']
        try:
            reader = make_reader(**reader_args)
        except StorageError as e:
            abort("{}: {}", reader_args['url'], e)
        click.get_current_context().call_on_close(reader.close)
        return fn(reader, *args, **kwargs)

    return wrapper


@click.group(context_settings=dict(auto_envvar_prefix=app_name.upper()))
@click.option(
    '--url',
    '--db',
    show_envvar=True,
    type=click.Path(dir_okay=False, resolve_path=True),
    show_default=True,
    default=os.path.join(app_dir, 'db.sqlite'),
    help="Path to the reader database.",
)
@click.option(
    '--feed-root',
    type=click.Path(file_okay=False),
    show_default=True,
    help=(
        "Directory local feeds are relative to. "
        "'' (empty string) means full filesystem access. "
        "If not provided, don't open local feeds."
    ),
)
@click.option(
    '--plugin',
    'plugins',
    show_envvar=True,
    multiple=True,
    callback=extend_defaults,
    help="Import path to a reader plug-in. Can be passed multiple times.",
)
@click.option(
    '--cli-plugin',
    'cli_plugins',
    show_envvar=True,
    multiple=True,
    callback=extend_defaults,
    help="Import path to a CLI plug-in. Can be passed multiple times.",
)
@config_option(
    '--config',
    show_default=True,
    default=os.path.join(app_dir, 'config.toml'),
    help="Path to the reader config.",
)
@click.version_option(reader.__version__, message='%(prog)s %(version)s')
@click.pass_context
def cli(ctx, url, plugins, cli_plugins, feed_root):
    """reader command-line interface.

    Option defaults can be set via environment variables;
    unless documented otherwise, the format is READER[_SUBCOMMAND]_OPTION.

    https://reader.readthedocs.io/

    """
    if os.path.commonpath([app_dir, url]) == app_dir:
        try:
            os.makedirs(app_dir, exist_ok=True)
        except Exception as e:
            abort("{}", e)

    PluginLoader('init_cli').oneshot(ctx.find_root().default_map, cli_plugins)


@cli.command()
@click.argument('url')
@click.option('--update/--no-update', help="Update the feed after adding it.")
@log_verbose
@pass_reader
def add(reader, url, update):
    """Add a new feed."""
    reader.add_feed(url)
    if update:
        reader.update_feed(url)


@cli.command()
@click.argument('url')
@log_verbose
@pass_reader
def delete(reader, url):
    """Delete an existing feed."""
    reader.delete_feed(url)


def red(text):
    return click.style(str(text), fg='bright_red')


def green(text):
    return click.style(str(text), fg='bright_green')


def iter_update_status(it, length):
    start = datetime.now()

    for i, result in enumerate(it):
        elapsed = datetime.now() - start
        pos = f"{i}/{length or '?'}"

        if result.not_modified:
            status = 'not modified'
            if result.updated_feed:
                status += f", {result.value.total} total"
        elif result.error:
            status = red(result.error)
            if isinstance(result.error, reader.UpdateHookError):
                log.error("got hook error; traceback follows", exc_info=result.error)
        else:
            status = green(
                f"{result.value.new} new, "
                f"{result.value.modified} modified, "
                f"{result.value.total} total"
            )

        click.echo(f"{elapsed}\t{pos}\t{result.url}\t{status}")

        yield result


@cli.command()
@click.argument('url', required=False)
@click.option(
    '--new/--no-new',
    '--new-only',
    default=None,
    help="Only update new (never updated before) feeds.",
)
@click.option(
    '--scheduled/--no-scheduled',
    default=True,
    show_default=True,
    help="Only update feeds scheduled to be updated.",
)
@click.option(
    '--workers',
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Number of threads to use when getting the feeds.",
)
@make_log_verbose(True, -2)
@log_command
@pass_reader
def update(reader, url, new, scheduled, workers, verbose):
    """Update one or all feeds.

    If URL is not given, update all the feeds.

    Verbosity works like this:

    \b
        : progress bar + final status
        -v: + lines
        -vv: + warnings
        -vvv: + info
        -vvvv: + debug

    """
    it = reader.update_feeds_iter(
        feed=url, new=new, scheduled=scheduled, workers=workers
    )
    length = reader.get_feed_counts(
        feed=url, new=new, scheduled=scheduled, updates_enabled=True
    ).total

    ok_count = 0
    not_modified_count = 0
    error_count = 0
    new_count = 0
    updated_count = 0

    def feed_stats(width=None):
        if not width:
            width, _ = shutil.get_terminal_size()
        if width < 80:
            return ''
        if width < 105:
            return f"{green(ok_count)}/{red(error_count)}/{not_modified_count}"
        return (
            f"{green(f'{ok_count} ok') if ok_count else '0 ok'}, "
            f"{red(f'{error_count} error') if error_count else '0 error'}, "
            f"{not_modified_count} not modified"
        )

    if not verbose:
        bar_context = click.progressbar(
            it,
            length=length,
            label='update',
            show_pos=True,
            show_eta=True,
            item_show_func=lambda _: feed_stats(),
            file=sys.stderr,
        )

    else:
        bar_context = nullcontext(iter_update_status(it, length))

    try:
        with bar_context as bar:
            for result in bar:
                if result.not_modified:
                    not_modified_count += 1
                elif result.error:
                    error_count += 1
                else:
                    ok_count += 1
                    new_count += result.value.new
                    updated_count += result.value.modified
    finally:
        click.echo(
            f"{feed_stats(9999)}; entries: {new_count} new, {updated_count} modified"
        )


@cli.group('list')
def list_cmd():
    """List feeds or entries."""


@list_cmd.command()
@pass_reader
def feeds(reader):
    """List all the feeds."""
    for feed in reader.get_feeds():
        click.echo(feed.url)


@list_cmd.command()
@pass_reader
def entries(reader):
    """List all the entries.

    Outputs one line per entry in the following format:

        <feed URL> <entry link or id>

    """
    for entry in reader.get_entries():
        click.echo(f"{entry.feed.url} {entry.link or entry.id}")


@cli.group()
def search():
    """Search commands."""


@search.command('status')
@pass_reader
def search_status(reader):
    """Check search status."""
    click.echo(f"search: {'enabled' if reader.is_search_enabled() else 'disabled'}")


@search.command('enable')
@pass_reader
def search_enable(reader):
    """Enable search."""
    reader.enable_search()


@search.command('disable')
@pass_reader
def search_disable(reader):
    """Disable search."""
    reader.disable_search()


@search.command('update')
@log_verbose
@log_command
@pass_reader
def search_update(reader):
    """Update the search index."""
    reader.update_search()


@search.command('entries')
@click.argument('query')
@pass_reader
def search_entries(reader, query):
    """Search entries.

    Outputs one line per entry in the following format:

        <feed URL> <entry link or id>

    """
    for rv in reader.search_entries(query):
        entry = reader.get_entry(rv)
        click.echo(f"{entry.feed.url} {entry.link or entry.id}")


try:
    import reader._app.cli
except ImportError:
    pass
else:
    cli.add_command(reader._app.cli.cli)


if __name__ == '__main__':
    cli()
