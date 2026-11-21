"""Профиль данных сквозного примера: почему приёмка по одному сентябрю ничего не доказывает."""
from __future__ import annotations

import duckdb

SEPT_GOLDEN = ("SELECT store_id, sum(amount) FROM raw.sales WHERE abs(qty) < 1000 "
               "AND sale_date BETWEEN '2026-09-01' AND '2026-09-30' GROUP BY 1 ORDER BY 1")
SEPT_NAIVE = ("SELECT store_id, sum(amount) FROM raw.sales "
              "WHERE sale_date BETWEEN '2026-09-01' AND '2026-09-30' GROUP BY 1 ORDER BY 1")
AUG2 = "SELECT sum(amount) FROM raw.sales WHERE store_id = 2 AND sale_date BETWEEN '2026-08-01' AND '2026-08-31'"


def profile(con: duckdb.DuckDBPyConnection) -> dict:
    by_month = con.execute(
        "SELECT strftime(sale_date, '%Y-%m'), count(*) FROM raw.sales "
        "WHERE abs(qty) >= 1000 AND sale_date >= '2026-01-01' GROUP BY 1 ORDER BY 1").fetchall()
    return {
        "scanner_error_rows": con.execute("SELECT count(*) FROM raw.sales WHERE abs(qty) >= 1000").fetchone()[0],
        "scanner_error_rows_2026": {m: n for m, n in by_month},
        "last_sale_date": con.execute("SELECT max(sale_date) FROM raw.sales").fetchone()[0].isoformat(),
        "september_by_store_without_rules_equals_golden":
            con.execute(SEPT_GOLDEN).fetchall() == con.execute(SEPT_NAIVE).fetchall(),
        "august_store2_without_rules": float(con.execute(AUG2).fetchone()[0]),
        "august_store2_golden": float(con.execute(AUG2 + " AND abs(qty) < 1000").fetchone()[0]),
        # чем объясняются ошибки варианта A: те же запросы без правил компании
        "q3_returns_share_without_rules": round(float(con.execute(
            "SELECT 100.0 * -sum(amount) FILTER (WHERE qty < 0) / sum(amount) FILTER (WHERE qty > 0) "
            "FROM raw.sales WHERE sale_date BETWEEN '2026-07-01' AND '2026-09-30'").fetchone()[0]), 4),
        "east_october_1_10": float(con.execute(
            "SELECT sum(s.amount) FROM raw.sales s JOIN raw.stores st USING (store_id) "
            "WHERE abs(s.qty) < 1000 AND st.region = 'Восток' AND s.sale_date >= '2026-10-01'").fetchone()[0]),
    }
