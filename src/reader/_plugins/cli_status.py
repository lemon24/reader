"""
cli_status
~~~~~~~~~~

Capture the stdout of a CLI command and add it as an entry to a special feed.

The feed URL is ``reader:status``; if it does not exist, it is created.

The entry id is the command, without options or arguments::

    ('reader:status', 'command: update')
    ('reader:status', 'command: search update')

Entries are marked as read.

To load::

    READER_CLI_PLUGIN='reader._plugins.cli_status.init_cli' \\
    python -m reader ...

"""

import io
import shlex
import sys
from contextlib import redirect_stderr
from contextlib import redirect_stdout

import click

from reader import EntryNotFoundError
from reader import FeedExistsError
from reader._cli import dump_config
from reader._cli import format_tb
from reader._cli import pass_reader


class Tee:
    def __init__(self, *files):
        self.files = files

    def write(self, data):
        for file in self.files:
            file.write(data)

    def flush(self):
        for file in self.files:
            file.flush()


FEED = 'reader:status'


def save_output(reader, config, command_path, output):
    now = reader._now()

    feed_url = FEED
    entry_id = f"command: {' '.join(command_path)}"

    content = get_output(config, now, output, sys.exc_info()[1])

    try:
        reader.add_feed(feed_url, allow_invalid_url=True)
        reader.disable_feed_updates(feed_url)
    except FeedExistsError:
        pass

    try:
        reader.delete_entry((feed_url, entry_id))
    except EntryNotFoundError:
        pass

    reader.add_entry(
        dict(
            feed_url=feed_url,
            id=entry_id,
            title=entry_id,
            content=[dict(type='text/plain', value=content)],
        )
    )
    reader.mark_entry_as_read((feed_url, entry_id))


def get_output(config, now, output, exc):
    code = 0
    tb = ''
    if not exc:
        pass
    elif isinstance(exc, click.exceptions.Exit):
        code = exc.exit_code
    elif isinstance(exc, SystemExit):
        code = exc.code
    else:
        code = 1
        tb = format_tb(exc)

    parts = [
        '# ' + now.replace(tzinfo=None).isoformat(' ', 'seconds'),
        'OK' if code == 0 else f'fail ({code})',
        '\n## output',
    ]
    output = output.rstrip()
    if output:
        parts.append(output)
    parts.extend(
        [
            '\n## argv',
            '\n'.join(map(shlex.quote, sys.argv[1:])),
            '\n## config',
            dump_config(config.merge_all().data.get('cli')).rstrip(),
        ]
    )

    if tb:
        parts.extend(['\n# traceback', tb.rstrip()])

    parts.append('\n')
    return '\n\n'.join(parts)


def init_cli(config):
    ctx = click.get_current_context()
    command = ctx.command

    command_path = []

    def add_trace(command):
        callback = command.callback

        def wrapper(*args, **kwargs):
            command_path.append(command.name)
            if callback:
                return callback(*args, **kwargs)

        command.callback = wrapper

        subcommands = list(getattr(command, 'commands', {}).values())
        for subcommand in subcommands:
            add_trace(subcommand)

    add_trace(command)

    output = io.StringIO()
    ctx.with_resource(redirect_stdout(Tee(sys.stdout, output)))
    ctx.with_resource(redirect_stderr(Tee(sys.stderr, output)))

    @pass_reader
    def callback(reader):
        save_output(reader, config, command_path, output.getvalue())

    ctx.call_on_close(callback)
