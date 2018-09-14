
if __name__ == '__main__':
    try:
        from reader.cli import cli
        cli()
    except ImportError:
        import sys
        print("""\
Error: cannot import reader.cli

This might be due to missing dependencies. The command-line interface is
optional, use the 'cli' extra to install its dependencies:

    pip install reader[cli]
""", file=sys.stderr)
        raise
