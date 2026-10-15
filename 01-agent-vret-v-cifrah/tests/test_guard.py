import pytest

from razbor01.guard import SqlRejected, check_sql


@pytest.mark.parametrize("sql", [
    "SELECT sum(amount) FROM raw.sales",
    "WITH x AS (SELECT * FROM raw.sales) SELECT count(*) FROM x",
])
def test_select_from_allowed_schema_passes(con, sql):
    check_sql(con, sql, {"raw"})


@pytest.mark.parametrize("sql, msg", [
    ("DROP TABLE raw.sales", "только SELECT"),
    ("SELECT 1; SELECT 2", "ровно один"),
    ("SELECT * FROM mart.sales_daily", "недоступны"),
    ("SELECT * FROM sales", "недоступны"),
    ("SELEC broken", "не разобран"),
])
def test_rejected(con, sql, msg):
    with pytest.raises(SqlRejected, match=msg):
        check_sql(con, sql, {"raw"})
