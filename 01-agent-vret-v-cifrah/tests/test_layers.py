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


def test_gross_minus_returns_is_net(con):
    net, ret, gross = con.execute("""SELECT sum(net_amount), sum(return_amount), sum(net_amount + return_amount)
                                     FROM mart.sales_daily""").fetchone()
    assert ret > 0 and gross - ret == net
