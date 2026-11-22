"""Слой метрик и агент пакета 01 работают поверх витрин этого пакета без правок."""
from datetime import date, timedelta

from razbor01.metrics import MetricQuery, compile_query

from razbor08.agent_bridge import catalog_01, metric
from razbor08.dwh import Warehouse
from razbor08.source import DocFilter, export_time

from .conftest import START


def test_revenue_by_region_matches_source(src, tmp_path):
    day = START - timedelta(days=1)
    wh = Warehouse(":memory:")
    src.export(tmp_path / "b", export_time(day), DocFilter.all())
    wh.load_batch(tmp_path / "b")
    wh.build_marts(day)
    cat = catalog_01(closed_through=date(2026, 9, 30))
    sql, params = compile_query(cat, MetricQuery("revenue", date(2026, 9, 1), date(2026, 9, 30), ("region",)))
    got = dict(wh.con.execute(sql, params).fetchall())
    want = dict(src.con.execute("""
        SELECT st.region, sum(l.amount) FROM ib.docs d JOIN ib.doc_lines l ON l.doc_ref = d.ref
        JOIN ib.stores st ON st.ref = d.store_ref
        WHERE d.doc_type = 'РозничныеПродажи' AND d.posted AND NOT d.deletion_mark
          AND d.doc_date BETWEEN DATE '2026-09-01' AND DATE '2026-09-30' GROUP BY 1""").fetchall())
    assert got == want
    # то же через обёртку, которой пользуется команда razbor08 metric
    rows = metric(wh, "stock_end_units", date(2026, 9, 1), date(2026, 9, 30), group_by=("store_id",),
                  closed_through=date(2026, 9, 30))
    assert len(rows) == 3 and all(r[1] is not None for r in rows)
    wh.close()
