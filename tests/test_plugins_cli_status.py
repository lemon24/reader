import re

import pytest
from click.testing import CliRunner

from reader._cli import cli
from test_cli import patch_app_dir
from utils import utc_datetime as datetime


@pytest.mark.slow
def test_cli_status(db_path, data_dir, make_reader, monkeypatch):
    monkeypatch.setattr('sys.argv', ['zero', 'one', 'two'])

    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(
            cli,
            ('--db', db_path, '--feed-root', str(data_dir)) + args,
            catch_exceptions=False,
        )

    reader = make_reader(db_path, feed_root=str(data_dir))
    reader.add_feed('full.rss')

    monkeypatch.setattr(
        'reader.Reader._now', staticmethod(lambda: datetime(2010, 1, 1, 0, 2))
    )
    result = invoke(
        '--cli-plugin', 'reader._plugins.cli_status.init_cli', 'update', '-v'
    )
    assert result.exit_code == 0, result.output
    assert 'full.rss' in result.output

    entry = reader.get_entry(('reader:status', 'command: update'))
    assert entry.title == 'command: update'
    assert result.output in entry.content[0].value

    assert entry.content[0].value.replace(result.output, '<OUTPUT>\n') == OUTPUT


OUTPUT = """\
# 2010-01-01 00:02:00

OK

<OUTPUT>


"""


@pytest.mark.slow
def test_many_runs(db_path, make_reader, monkeypatch):
    runner = CliRunner(mix_stderr=False)

    def invoke(*args):
        return runner.invoke(cli, ('--db', db_path) + args, catch_exceptions=False)

    reader = make_reader(db_path)

    nows = [
        datetime(2009, 12, 31, 22, 59),
        datetime(2009, 12, 31, 23),
        datetime(2010, 1, 1),
        datetime(2010, 1, 1, 0, 2),
        datetime(2010, 1, 1, 0, 59),
        datetime(2010, 1, 1, 23),
    ]

    for now in nows:
        monkeypatch.setattr('reader.Reader._now', staticmethod(lambda: now))
        result = invoke(
            '--cli-plugin',
            'reader._plugins.cli_status.init_cli',
            'update',
        )
        assert result.exit_code == 0, result.output

    (entry,) = reader.get_entries(feed='reader:status')

    assert entry.id == "command: update"
    assert entry.updated == datetime(2010, 1, 1, 23)

    value = entry.content[0].value

    assert re.findall('^# .*', value, re.M) == [
        '# 2010-01-01 23:00:00',
        '# 2010-01-01 00:59:00',
        '# 2010-01-01 00:02:00',
        '# 2010-01-01 00:00:00',
        '# 2009-12-31 23:00:00',
    ]
    # '# 2009-12-31 22:59:00' gets deleted!

    assert value.replace(result.stdout, '<OUTPUT>\n').startswith(MANY_RUNS_PREFIX)


MANY_RUNS_PREFIX = """\
# 2010-01-01 23:00:00

OK

<OUTPUT>


# 2010-01-01 00:59:00

OK

<OUTPUT>


"""
