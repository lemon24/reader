import re

import pytest
from click.testing import CliRunner

from reader._cli import cli
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

    entry = reader.get_entry(('reader:status', 'command: update @ 2010-01-01 00'))
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
    runner = CliRunner()

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

    actual = []
    for e in reader.get_entries(feed='reader:status'):
        actual.append((e.id, e.updated, re.findall('^# .*', e.content[0].value, re.M)))

    assert actual == [
        (
            'command: update @ 2010-01-01 23',
            datetime(2010, 1, 1, 23),
            ['# 2010-01-01 23:00:00'],
        ),
        (
            'command: update @ 2010-01-01 00',
            datetime(2010, 1, 1, 0, 59),
            [
                '# 2010-01-01 00:00:00',
                '# 2010-01-01 00:02:00',
                '# 2010-01-01 00:59:00',
            ],
        ),
        (
            'command: update @ 2009-12-31 23',
            datetime(2009, 12, 31, 23),
            ['# 2009-12-31 23:00:00'],
        ),
        # 'command: update 2009-12-31 22' gets deleted!
    ]
