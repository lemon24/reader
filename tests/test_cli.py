import pytest
import py.path
from click.testing import CliRunner

from reader.cli import cli
from reader import Reader


@pytest.mark.slow
def test_cli(db_path, data_dir):
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


def raise_exception_plugin(reader):
    assert isinstance(reader, Reader)
    raise Exception("plug-in error")

@pytest.mark.slow
def test_cli_plugin(db_path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, 'path', [str(py.path.local(__file__).dirpath())] + sys.path)

    runner = CliRunner()
    result = runner.invoke(cli, ['--db', db_path,
                                 '--plugin', 'test_cli:raise_exception_plugin',
                                 'list', 'feeds'])
    assert result.exit_code != 0
    assert "plug-in error" in result.output


@pytest.mark.slow
def test_cli_serve_calls_create_app(db_path, monkeypatch):

    exception = Exception("create_app error")

    def create_app(*args):
        assert args == (db_path, )
        raise exception

    monkeypatch.setattr('reader.app.create_app', create_app)

    runner = CliRunner()
    result = runner.invoke(cli, ['--db', db_path, 'serve'])

    assert result.exit_code != 0
    assert result.exception == exception

