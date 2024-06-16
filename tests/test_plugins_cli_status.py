import pytest
from click.testing import CliRunner

from reader._cli import cli


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

    result = invoke(
        '--cli-plugin', 'reader._plugins.cli_status.init_cli', 'update', '-v'
    )
    assert result.exit_code == 0, result.output
    assert 'full.rss' in result.output

    entry = reader.get_entry(('reader:status', 'command: update'))
    assert result.output in entry.content[0].value

    def clean_value(value, output):
        return (
            value.replace(output, '<OUTPUT>\n')
            .replace(db_path, '<DB>')
            .replace(str(data_dir), '<DATA>')
        )

    assert clean_value(entry.content[0].value, result.output) == OUTPUT


OUTPUT = """\
OK


# output

<OUTPUT>


# argv

one
two


# config

reader:
  url: <DB>
  feed_root: <DATA>
plugins:
  reader._plugins.cli_status.init_cli: null


"""
