import duckdb

from razbor06.profile import profile


def test_profile_shows_why_one_month_proves_nothing(db):
    con = duckdb.connect(str(db), read_only=True)
    try:
        p = profile(con)
    finally:
        con.close()
    assert p["scanner_error_rows"] == 40
    assert p["scanner_error_rows_2026"] == {"2026-08": 8}            # в сентябре строк-ошибок нет
    assert p["last_sale_date"] == "2026-10-10"
    assert p["september_by_store_without_rules_equals_golden"] is True
    assert p["august_store2_without_rules"] > 50 * p["august_store2_golden"]
    # ошибки варианта A в записанном прогоне 01 — ровно эти запросы без правил компании
    assert p["q3_returns_share_without_rules"] == 0.4845
    assert p["east_october_1_10"] == 392589.91
