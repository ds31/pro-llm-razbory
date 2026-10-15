def test_products_deduplicated(con):
    assert con.execute("SELECT count(*), count(DISTINCT sku) FROM mart.products").fetchone() == (200, 200)


def test_anomalies_removed(con):
    assert con.execute("SELECT count(*) FROM stg.sales WHERE abs(qty) >= 1000").fetchone()[0] == 0


def test_open_month_flagged_and_excluded(con):
    assert con.execute("SELECT is_closed FROM mart.months WHERE month = '2026-10-01'").fetchone()[0] is False
    assert con.execute("SELECT is_closed FROM mart.months WHERE month = '2026-09-01'").fetchone()[0] is True
    assert con.execute("SELECT max(sale_date) FROM mart.sales_daily").fetchone()[0].isoformat() == "2026-09-30"


def test_mart_revenue_equals_raw_with_rules(con):
    mart = con.execute("SELECT sum(net_amount) FROM mart.sales_daily WHERE month = '2026-09-01'").fetchone()[0]
    raw = con.execute("""SELECT sum(amount) FROM raw.sales
                         WHERE abs(qty) < 1000 AND sale_date BETWEEN '2026-09-01' AND '2026-09-30'""").fetchone()[0]
    assert mart == raw


def test_returns_match_raw_and_nonnegative(con):
    mart_ret = con.execute("SELECT sum(return_amount) FROM mart.sales_daily").fetchone()[0]
    raw_ret = con.execute("""SELECT -sum(r.amount) FROM raw.sales r
                             JOIN mart.months m ON m.month = date_trunc('month', r.sale_date) AND m.is_closed
                             WHERE r.qty < 0 AND abs(r.qty) < 1000""").fetchone()[0]
    assert mart_ret > 0 and mart_ret == raw_ret
    assert con.execute("SELECT count(*) FROM mart.sales_daily WHERE return_amount < 0").fetchone()[0] == 0
