import pytest
import py.path
from click.testing import CliRunner

from reader.cli import cli


@pytest.mark.slow
def test_cli(db_path):
    data_dir = py.path.local(__file__).dirpath().join('data')
    feed_filename = 'full.atom'
    feed_path = str(data_dir.join(feed_filename))

    expected = {}
    exec(data_dir.join(feed_filename + '.py').read(), expected)

    runner = CliRunner()

    result = runner.invoke(cli, ['--db', db_path, 'list', 'feeds'])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'add', feed_path])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'list', 'feeds'])
    assert result.exit_code == 0
    assert result.output.splitlines() == [feed_path]

    result = runner.invoke(cli, ['--db', db_path, 'list', 'entries'])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'update'])
    assert result.exit_code == 0
    assert result.output == ''

    result = runner.invoke(cli, ['--db', db_path, 'list', 'feeds'])
    assert result.exit_code == 0
    assert result.output.splitlines() == [feed_path]

    result = runner.invoke(cli, ['--db', db_path, 'list', 'entries'])
    assert result.exit_code == 0
    assert [l.split() for l in result.output.splitlines()] == [
        [feed_path, e.link or e.id]
        for e in
        sorted(expected['entries'], key=lambda e: e.updated, reverse=True)
    ]


