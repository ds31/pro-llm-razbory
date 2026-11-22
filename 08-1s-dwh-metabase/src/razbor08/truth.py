"""Эталон: те же цифры, посчитанные прямо по базе-источнику, минуя выгрузку и загрузчик.

snapshot() пишет три parquet-файла на момент выгрузки: продажи магазин × день, остаток на
последний день, остатки на конец каждого полного месяца. compare() сверяет с ними витрины.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

TOL = 0.005        # копейки: расхождение меньше полкопейки — не расхождение
MONTH_TOL = 0.005  # ±0,5 % выручки магазина за месяц


def snapshot(src, at: datetime, as_of: date, out_dir) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    c = src.con
    c.execute("""CREATE OR REPLACE TEMP TABLE t_docs AS SELECT * FROM ib.docs
                 WHERE posted AND NOT deletion_mark AND visible_at <= ?""", [at])
    paths = {k: (out / f"{k}.parquet").as_posix() for k in ("sales", "stock", "month_end")}
    c.execute(f"""COPY (
        SELECT st.code AS store_id, d.doc_date AS day, sum(l.qty)::BIGINT AS qty, sum(l.amount) AS amount
        FROM t_docs d JOIN ib.doc_lines l ON l.doc_ref = d.ref JOIN ib.stores st ON st.ref = d.store_ref
        WHERE d.doc_type = 'РозничныеПродажи' GROUP BY ALL) TO '{paths['sales']}' (FORMAT parquet)""")
    c.execute(f"""CREATE OR REPLACE TEMP TABLE t_mv AS
        SELECT st.code AS store_id, p.code AS sku, date_trunc('month', m.period)::DATE AS month,
               sum(CASE m.record_type WHEN 'Receipt' THEN m.qty ELSE -m.qty END)::BIGINT AS delta
        FROM ib.moves m JOIN t_docs d ON d.ref = m.recorder
        JOIN ib.stores st ON st.ref = m.store_ref JOIN ib.products p ON p.ref = m.product_ref
        WHERE m.period <= DATE '{as_of.isoformat()}' GROUP BY ALL""")
    c.execute(f"""COPY (SELECT store_id, sku, sum(delta)::BIGINT AS qty FROM t_mv GROUP BY ALL)
                  TO '{paths['stock']}' (FORMAT parquet)""")
    c.execute(f"""COPY (
        WITH months AS (SELECT range::DATE AS month FROM range((SELECT min(month) FROM t_mv),
                         date_trunc('month', DATE '{as_of.isoformat()}')::DATE, INTERVAL 1 MONTH)),
             grid AS (SELECT DISTINCT store_id, sku FROM t_mv)
        SELECT g.store_id, g.sku, m.month,
               sum(coalesce(t.delta, 0)) OVER (PARTITION BY g.store_id, g.sku ORDER BY m.month)::BIGINT AS qty
        FROM grid g CROSS JOIN months m LEFT JOIN t_mv t ON t.store_id = g.store_id AND t.sku = g.sku AND t.month = m.month
        ) TO '{paths['month_end']}' (FORMAT parquet)""")
    return paths


def compare(wh, snap: dict[str, str]) -> dict:
    """Сколько магазино-дней продаж и ячеек остатков разошлись с эталоном и на сколько рублей."""
    c = wh.con
    sales = c.execute(f"""
        WITH m AS (SELECT store_id, sale_date AS day, sum(net_qty) AS qty, sum(net_amount) AS amount
                   FROM mart.sales_daily GROUP BY ALL),
             t AS (SELECT * FROM read_parquet('{snap['sales']}'))
        SELECT count(*) FILTER (WHERE abs(coalesce(m.amount, 0) - coalesce(t.amount, 0)) > {TOL}
                                   OR coalesce(m.qty, 0) <> coalesce(t.qty, 0)),
               coalesce(sum(abs(coalesce(m.amount, 0) - coalesce(t.amount, 0))), 0),
               coalesce(sum(t.amount), 0), count(*)
        FROM m FULL JOIN t ON m.store_id = t.store_id AND m.day = t.day""").fetchone()
    stock = c.execute(f"""
        WITH m AS (SELECT store_id, sku, qty_on_hand AS qty FROM mart.stock_current),
             t AS (SELECT * FROM read_parquet('{snap['stock']}'))
        SELECT count(*) FILTER (WHERE coalesce(m.qty, 0) <> coalesce(t.qty, 0))
        FROM m FULL JOIN t ON m.store_id = t.store_id AND m.sku = t.sku""").fetchone()
    me = c.execute(f"""
        WITH m AS (SELECT store_id, sku, month, qty_on_hand AS qty FROM mart.stock_month_end),
             t AS (SELECT * FROM read_parquet('{snap['month_end']}'))
        SELECT count(*) FILTER (WHERE coalesce(m.qty, 0) <> coalesce(t.qty, 0))
        FROM m FULL JOIN t ON m.store_id = t.store_id AND m.sku = t.sku AND m.month = t.month""").fetchone()
    # месяц — единица отчёта и вопроса к агенту: допуск ±0,5 %, как в eval пакета 01
    months = c.execute(f"""
        WITH m AS (SELECT store_id, date_trunc('month', sale_date) AS month, sum(net_amount) AS amount
                   FROM mart.sales_daily GROUP BY ALL),
             t AS (SELECT store_id, date_trunc('month', day) AS month, sum(amount) AS amount
                   FROM read_parquet('{snap['sales']}') GROUP BY ALL),
             j AS (SELECT coalesce(m.month, t.month) AS month, coalesce(m.amount, 0) AS got, coalesce(t.amount, 0) AS want
                   FROM m FULL JOIN t ON m.store_id = t.store_id AND m.month = t.month)
        SELECT count(*) FILTER (WHERE abs(got - want) > {MONTH_TOL} * abs(want)),
               (SELECT 100 * (sum(got) - sum(want)) / sum(want) FROM j
                WHERE month = (SELECT max(month) FROM j) - INTERVAL 1 MONTH)
        FROM j""").fetchone()
    return {"store_months_bad": int(months[0]), "last_full_month_err_pct": round(float(months[1]), 3),
            "sales_days_bad": int(sales[0]), "revenue_abs_err": float(sales[1]),
            "revenue_total": float(sales[2]), "sales_days": int(sales[3]),
            "stock_cells_bad": int(stock[0]), "month_end_cells_bad": int(me[0])}
