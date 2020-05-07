from copy import deepcopy
from textwrap import dedent

import pytest

from reader._sql_utils import Query
from reader._sql_utils import ScrollingWindow


def test_query_simple():
    assert str(
        Query().SELECT('select').FROM('from').JOIN('join').WHERE('where')
    ) == dedent(
        """\
        SELECT
            select
        FROM
            from
        JOIN
            join
        WHERE
            where
        ;
        """
    )


def test_query_complicated():
    """Test a complicated query:

    * order between different (known) keywords does not matter
    * arguments of repeated calls get appended, with the order preserved
    * SELECT can receive 2-tuples
    * WHERE and HAVING arguments are separated by AND
    * JOIN arguments are separated by the keyword
    * no-argument keywords have no effect

    """
    assert str(
        Query()
        .WHERE()
        .OUTER_JOIN('outer join')
        .JOIN('join')
        .LIMIT('limit')
        .JOIN()
        .ORDER_BY('first', 'second')
        .SELECT('one')
        .HAVING('having')
        .SELECT(('two', 'expr'))
        .GROUP_BY('group by')
        .FROM('from')
        .SELECT('three', 'four')
        .FROM('another from')
        .WHERE('where')
        .ORDER_BY('third')
        .OUTER_JOIN('another outer join')
        .WITH('first cte')
        .GROUP_BY('another group by')
        .HAVING('another having')
        .WITH('second cte')
        .JOIN('another join')
        .WHERE('another where')
        .NATURAL_JOIN('natural join')
        .SELECT()
        .SELECT()
    ) == dedent(
        """\
        WITH
            first cte,
            second cte
        SELECT
            one,
            expr AS two,
            three,
            four
        FROM
            from,
            another from
        OUTER JOIN
            outer join
        OUTER JOIN
            another outer join
        JOIN
            join
        JOIN
            another join
        NATURAL JOIN
            natural join
        WHERE
            where AND
            another where
        GROUP BY
            group by,
            another group by
        HAVING
            having AND
            another having
        ORDER BY
            first,
            second,
            third
        LIMIT
            limit
        ;
        """
    )


def test_scrolling_window():
    simple_query = Query().SELECT('select').FROM('from')

    query = deepcopy(simple_query)
    scrolling_window = ScrollingWindow(query)
    assert str(query) == str(simple_query)

    query = deepcopy(simple_query)
    scrolling_window = ScrollingWindow(query, 'one')
    assert str(query) == str(deepcopy(simple_query).ORDER_BY('one ASC'))

    query = deepcopy(simple_query)
    scrolling_window = ScrollingWindow(query, 'one')
    scrolling_window.LIMIT('limit', last=False)
    assert str(query) == str(deepcopy(simple_query).ORDER_BY('one ASC').LIMIT('limit'))

    query = deepcopy(simple_query)
    scrolling_window = ScrollingWindow(query, 'one')
    scrolling_window.LIMIT('limit', last=True)
    assert str(query) == str(
        deepcopy(simple_query)
        .WHERE(
            """
            (
                one
            ) > (
                :last_0
            )
            """
        )
        .ORDER_BY('one ASC')
        .LIMIT('limit')
    )

    query = deepcopy(simple_query)
    scrolling_window = ScrollingWindow(query, 'one', desc=True, keyword='HAVING')
    scrolling_window.LIMIT('limit', last=True)
    assert str(query) == str(
        deepcopy(simple_query)
        .HAVING(
            """
            (
                one
            ) < (
                :last_0
            )
            """
        )
        .ORDER_BY('one DESC')
        .LIMIT('limit')
    )


def test_scrolling_window_extract_last():
    query = Query().SELECT('one', 'two', 'three').FROM('from')
    scrolling_window = ScrollingWindow(query, 'one', 'three')
    assert scrolling_window.extract_last([1, 2, 3]) == [('last_0', 1), ('last_1', 3)]
