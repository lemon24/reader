"""
Extract query timings from (stderr) log output of:

    reader --debug-storage [update | update --new-only | search update] --vv

Note that the timings are not entirely accurate:

* for SELECTs, a read lock may be still held after cursor.execute() returns
* we don't know how long transactions take; BEGIN IMMEDIATE tells us how long
  it waited for a write lock; BEGIN (DEFERRED) doesn't tell us anything,
  since the locks are acquired by a subsequent statement

Nevertheless, we can at least see how much things wait for locks,
and how often they time out.

Initially made for #175 and #178.

"""
import json
import re
import sys
from functools import partial
from itertools import chain
from itertools import groupby
from typing import NamedTuple

import click
import numpy as np
from tabulate import tabulate


# assumes dict()s are ordered

value_funcs = {
    'duration': lambda d: d['duration'],
    'read_count': lambda d: d['io_counters']['read_count'],
    'write_count': lambda d: d['io_counters']['write_count'],
    'read_mib': lambda d: d['io_counters']['read_bytes'] / 2 ** 20,
    'write_mib': lambda d: d['io_counters']['write_bytes'] / 2 ** 20,
}

# TODO: move into value_funcs
value_ndigits = {
    'duration': 4,
    'read_count': 1,
    'write_count': 1,
    'read_mib': 3,
    'write_mib': 3,
}

agg_funcs = {
    'n': len,
    'sum': sum,
    'avg': np.mean,
    'min': min,
    'p50': partial(np.quantile, q=0.5),
    'p90': partial(np.quantile, q=0.9),
    'p95': partial(np.quantile, q=0.95),
    'p99': partial(np.quantile, q=0.99),
    'max': max,
}


class Result(NamedTuple):
    file: str
    func: str
    stmt: str
    exc: str
    values: tuple


def clean_up_stmt(stmt):
    stmt = re.sub('\s+', ' ', stmt).strip()

    values = re.escape('(?, ?)')
    stmt = re.sub(
        f'AS \( VALUES {values}(, {values})*', 'AS ( VALUES (?, ?), ...', stmt
    )

    if stmt.startswith('SELECT') and ' FROM ' in stmt:
        stmt = stmt.split()
        stmt = stmt[: stmt.index('FROM') + 2] + (['...'] if stmt[-2] != 'FROM' else [])
        stmt = ' '.join(stmt)

    return stmt


def parse_results(lines):
    for line in lines:
        if '"method": ' not in line:
            continue
        parts = line.split(maxsplit=3)
        try:
            data = json.loads(parts[3])
        except json.JSONDecodeError:
            print('---', parts[3])
            raise

        if not data['method'].startswith('execute'):
            continue

        file, func = data['caller']
        stmt = clean_up_stmt(data['stmt'])
        exc = data.get('exception', '')
        values = tuple(fn(data) for fn in value_funcs.values())

        yield Result(file, func, stmt, exc, values)


def make_table(ts):
    columns = list(zip(*ts))
    rows = [
        [fn] + [round(f(c), nd) for c, nd in zip(columns, value_ndigits.values())]
        for fn, f in agg_funcs.items()
    ]
    return rows


def make_tables(results):
    results = sorted(results)
    results_grouped = (
        (k, (r.values for r in rs)) for k, rs in groupby(results, lambda r: r[:4])
    )
    for key, ts in results_grouped:
        yield key, make_table(ts)


@click.command()
@click.option('-s', '--sort', type=click.Choice(list(value_funcs)), default=None)
@click.option('-t', '--totals/--no-totals')
def main(sort, totals):
    results = list(parse_results(sys.stdin))
    tables = make_tables(results)

    if sort:
        agg_index = list(agg_funcs).index('sum')
        value_index = list(value_funcs).index(sort)
        key = lambda t: t[1][agg_index][value_index + 1]
        tables = sorted(tables, key=key, reverse=True)

    if totals:
        tables = chain(
            [
                (
                    ('<no file>', '<no func>', '<total>', ''),
                    make_table(r.values for r in results),
                ),
            ],
            tables,
        )

    for (file, func, stmt, exc), rows in tables:
        print(file.rpartition('/')[2], func)

        short_stmt = ' '.join(stmt.split()[:5])
        if short_stmt != stmt and not short_stmt.endswith('...'):
            short_stmt += ' ...'
        print(short_stmt)

        print(exc or '<no exc>')

        print(tabulate(rows, headers=value_funcs, tablefmt='plain', floatfmt='.9g'))
        print()


if __name__ == '__main__':
    main()
