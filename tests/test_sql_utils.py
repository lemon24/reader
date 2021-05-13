from copy import deepcopy
from textwrap import dedent

import pytest

from reader._sql_utils import BaseQuery
from reader._sql_utils import Query


def test_query_simple():
    query = BaseQuery().SELECT('select').FROM('from').JOIN('join').WHERE('where')
    assert str(query) == dedent(
        """\
        SELECT
            select
        FROM
            from
        JOIN
            join
        WHERE
            where
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
    query = (
        BaseQuery()
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
        # this isn't technically valid
        .WITH('first cte')
        .GROUP_BY('another group by')
        .HAVING('another having')
        .WITH(('fancy', 'second cte'))
        .JOIN('another join')
        .WHERE('another where')
        .NATURAL_JOIN('natural join')
        .SELECT()
        .SELECT()
    )
    assert str(query) == dedent(
        """\
        WITH
            (
                first cte
            ),
            fancy AS (
                second cte
            )
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
        JOIN
            join
        OUTER JOIN
            another outer join
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
        """
    )


def test_query_flag():
    query = BaseQuery().SELECT('one').SELECT('two').SELECT_DISTINCT()
    assert str(query) == dedent(
        """\
        SELECT DISTINCT
            one,
            two
        """
    )
    with pytest.raises(ValueError):
        BaseQuery().SELECT_MAGIC('one')


def test_query_deepcopy():
    deepcopy(Query())


def test_scrolling_window():
    def make_query(cls=Query):
        return cls().SELECT('select').FROM('from')

    query = make_query()
    query.scrolling_window_order_by()
    assert str(query) == str(make_query(BaseQuery))

    query = make_query()
    query.scrolling_window_order_by('one')
    assert str(query) == str(make_query(BaseQuery).ORDER_BY('one ASC'))

    query = make_query()
    query.LIMIT('limit')
    assert str(query) == str(make_query(BaseQuery).LIMIT('limit'))

    query = make_query()
    query.scrolling_window_order_by('one')
    query.LIMIT('limit')
    assert str(query) == str(make_query(BaseQuery).ORDER_BY('one ASC').LIMIT('limit'))

    query = make_query()
    query.scrolling_window_order_by('one')
    query.LIMIT('limit')
    query.add_last([])
    assert str(query) == str(
        make_query(BaseQuery)
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

    query = make_query()
    query.scrolling_window_order_by('one', desc=True, keyword='HAVING')
    query.LIMIT('limit')
    query.add_last([])
    assert str(query) == str(
        make_query(BaseQuery)
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


def test_scrolling_window_last():
    query = Query().SELECT()
    query.scrolling_window_order_by()
    assert query.extract_last([1, 2, 3]) == None
    assert dict(query.add_last(None)) == {}

    query = Query().SELECT('one', 'two', ('three', 'max(3)'))
    query.scrolling_window_order_by('one', 'three')
    assert query.extract_last([1, 2, 3]) == (1, 3)
    assert dict(query.add_last([1, 3])) == {'last_0': 1, 'last_1': 3}
