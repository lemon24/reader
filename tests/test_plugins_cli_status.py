import pytest
from click.testing import CliRunner

from reader._cli import cli


@pytest.mark.slow
def test_cli_status(db_path, data_dir, make_reader):
    runner = CliRunner()

    def invoke(*args):
        return runner.invoke(
            cli, ('--db', db_path, '--feed-root', str(data_dir)) + args
        )

    reader = make_reader(db_path, feed_root=str(data_dir))
    reader.add_feed('full.rss')

    result = invoke(
        '--cli-plugin', 'reader._plugins.cli_status.init_cli', 'update', '-v'
    )
    assert result.exit_code == 0
    assert 'full.rss' in result.output

    entry = reader.get_entry(('reader:status', 'command: update'))
    assert result.output in entry.content[0].value
