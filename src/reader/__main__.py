import sys

CANNOT_IMPORT = """\
Error: cannot import reader._cli

This might be due to missing dependencies. The command-line interface is
optional, use the 'cli' extra to install its dependencies:

    pip install reader[cli]
"""

try:
    from reader._cli import cli

    cli(prog_name='python -m reader')
except ImportError:
    print(CANNOT_IMPORT, file=sys.stderr)
    raise
