import math
from datetime import date

import pytest

from conftest import ROOT
from razbor01.metrics import MetricError, MetricQuery, compile_query, load_catalog


@pytest.fixture(scope="module")
def cat():
    return load_catalog(ROOT / "metrics.yaml")


def value(con, cat, **kw):
    sql, params = compile_query(cat, MetricQuery(**kw))
    got = float(con.execute(sql, params).fetchone()[-1])
    assert math.isfinite(got)
    return got


def test_catalog_loads(cat):
    assert cat.closed_through == date(2026, 9, 30)
    assert {"revenue", "gross_sales", "returns_amount", "units", "avg_unit_price",
            "active_stores", "stock_end_units", "stock_avg_units"} <= set(cat.metrics)
    assert [r["id"] for r in cat.rules] == ["R1", "R2", "R3", "R4", "R5"]


def test_revenue_with_filter(con, cat):
    got = value(con, cat, metric="revenue", date_from=date(2026, 9, 1), date_to=date(2026, 9, 30),
                filters={"category": ["Напитки"]})
    exp = con.execute("""SELECT sum(s.amount) FROM raw.sales s
                         JOIN (SELECT DISTINCT sku, category FROM raw.products) p USING (sku)
                         WHERE abs(s.qty) < 1000 AND p.category = 'Напитки'
                           AND s.sale_date BETWEEN '2026-09-01' AND '2026-09-30'""").fetchone()[0]
    assert got > 0
    assert got == pytest.approx(float(exp))


def test_group_by_month(con, cat):
    sql, params = compile_query(cat, MetricQuery("revenue", date(2026, 1, 1), date(2026, 3, 31), group_by=("month",)))
    rows = con.execute(sql, params).fetchall()
    assert [str(r[0]) for r in rows] == ["2026-01-01", "2026-02-01", "2026-03-01"]


def test_stock_end_takes_last_month_only(con, cat):
    got = value(con, cat, metric="stock_end_units", date_from=date(2026, 7, 1), date_to=date(2026, 9, 30))
    exp = con.execute("SELECT sum(qty_on_hand) FROM raw.stock WHERE snapshot_date = '2026-09-30'").fetchone()[0]
    assert got > 0
    assert got == exp


def test_stock_avg_is_mean_of_month_totals(con, cat):
    got = value(con, cat, metric="stock_avg_units", date_from=date(2026, 1, 1), date_to=date(2026, 6, 30))
    exp = con.execute("""SELECT avg(t) FROM (SELECT snapshot_date, sum(qty_on_hand) t FROM raw.stock
                         WHERE snapshot_date BETWEEN '2026-01-01' AND '2026-06-30' GROUP BY 1)""").fetchone()[0]
    assert got > 0
    assert got == pytest.approx(exp)


def test_open_month_rejected(cat):
    with pytest.raises(MetricError, match="незакрытый"):
        compile_query(cat, MetricQuery("revenue", date(2026, 10, 1), date(2026, 10, 31)))


def test_unknown_metric_and_dimension_rejected(cat):
    with pytest.raises(MetricError, match="нет метрики"):
        compile_query(cat, MetricQuery("profit", date(2026, 1, 1), date(2026, 1, 31)))
    with pytest.raises(MetricError, match="не режется"):
        compile_query(cat, MetricQuery("stock_end_units", date(2026, 1, 1), date(2026, 1, 31), group_by=("month",)))


def test_reversed_period_rejected(cat):
    with pytest.raises(MetricError, match="позже"):
        compile_query(cat, MetricQuery("revenue", date(2026, 3, 1), date(2026, 1, 31)))


def test_filter_values_are_parameters_not_sql(con, cat):
    sql, params = compile_query(cat, MetricQuery("revenue", date(2026, 9, 1), date(2026, 9, 30),
                                                 filters={"region": ["Юг' OR 1=1 --"]}))
    assert "OR 1=1" not in sql
    assert con.execute(sql, params).fetchone()[0] is None


def test_closed_through_matches_mart_months(db_path, con):
    last = con.execute("SELECT max(month) FROM mart.months WHERE is_closed").fetchone()[0]
    nxt = date(last.year + (last.month == 12), last.month % 12 + 1, 1)
    last_day = date.fromordinal(nxt.toordinal() - 1)
    assert load_catalog(ROOT / "metrics.yaml").closed_through == last_day


def test_empty_filter_list_rejected(cat):
    with pytest.raises(MetricError, match="пуст"):
        compile_query(cat, MetricQuery("revenue", date(2026, 1, 1), date(2026, 1, 31), filters={"region": []}))


def test_duplicate_group_by_rejected(cat):
    with pytest.raises(MetricError, match="повтор"):
        compile_query(cat, MetricQuery("revenue", date(2026, 1, 1), date(2026, 1, 31), group_by=("region", "region")))
