"""
cli_status
~~~~~~~~~~

Capture the output of a CLI command and add it as an entry to a special feed.

The feed URL is ``reader:status``; if it does not exist, it is created.

The entry id is the command, without options or arguments::

    ('reader:status', 'command: update')
    ('reader:status', 'command: search update')

Entries contain the output of all the runs in the past 24 hours.
Entries are marked as read.

To load::

    READER_CLI_PLUGIN='reader._plugins.cli_status.init_cli' \\
    python -m reader ...

"""

import io
import re
import shlex
import sys
from contextlib import redirect_stdout
from datetime import datetime
from datetime import timedelta

import click

from reader import EntryNotFoundError
from reader import FeedExistsError
from reader import Reader
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
MAX_HOURS = 24


def save_output(reader, now, config, command_path, output):
    now_naive = now.replace(tzinfo=None)

    feed_url = FEED
    title = f"command: {' '.join(command_path)}"
    entry_id = title

    content = get_output(config, now, output, sys.exc_info()[1])

    try:
        reader.add_feed(feed_url, allow_invalid_url=True)
        reader.disable_feed_updates(feed_url)
    except FeedExistsError:
        pass

    try:
        old_content = reader.get_entry((feed_url, entry_id)).content[0].value
    except EntryNotFoundError:
        old_content = ''

    parts = [content]
    parts.extend(
        output
        for added, output in parse_output(old_content)
        if added >= now_naive - timedelta(hours=MAX_HOURS)
    )

    reader.add_entry(
        dict(
            feed_url=feed_url,
            id=entry_id,
            title=title,
            updated=now,
            content=[dict(type='text/plain', value=''.join(parts))],
        ),
        overwrite=True,
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
    ]
    output = output.rstrip()
    if output:
        parts.append(output)

    if tb:
        parts.extend(
            [
                '\n## traceback',
                tb.rstrip(),
                '\n## argv',
                '\n'.join(map(shlex.quote, sys.argv[1:])),
                '\n## config',
                dump_config(config.merge_all().data.get('cli')).rstrip(),
            ]
        )

    parts.append('\n')
    return '\n\n'.join(parts)


HEADING = r'# (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\n'
SECTION = rf'{HEADING}.*?(?=(?:{HEADING})|$)'
SECTION_RE = re.compile(SECTION, re.DOTALL)


def parse_output(output):
    for match in SECTION_RE.finditer(output):
        yield datetime.fromisoformat(match.group(1)), match.group(0)


def init_cli(config):
    now = Reader._now()

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

    @pass_reader
    def callback(reader):
        save_output(reader, now, config, command_path, output.getvalue())

    ctx.call_on_close(callback)
