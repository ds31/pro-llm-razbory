import duckdb

from razbor01.synth import ANOMALY_QTY, ANOMALY_STORE, AS_OF, generate


def test_raw_tables_and_period(con):
    tables = {r[0] for r in con.execute(
        "SELECT schema_name || '.' || table_name FROM duckdb_tables()").fetchall()}
    assert {"raw.stores", "raw.products", "raw.sales", "raw.stock"} <= tables
    first, last = con.execute("SELECT min(sale_date), max(sale_date) FROM raw.sales").fetchone()
    assert str(first) == "2024-10-01" and last == AS_OF
    months = con.execute("SELECT count(DISTINCT date_trunc('month', snapshot_date)) FROM raw.stock").fetchone()[0]
    assert months == 24


def test_trap_duplicate_products(con):
    total, distinct = con.execute("SELECT count(*), count(DISTINCT sku) FROM raw.products").fetchone()
    assert (total, distinct) == (210, 200)
    cats = con.execute("""SELECT count(DISTINCT category) FROM raw.products
                          WHERE sku IN (SELECT sku FROM raw.products GROUP BY sku HAVING count(*) > 1)""").fetchone()[0]
    assert cats == 6, "дубли должны быть в каждой категории"


def test_trap_open_month_has_sales_but_no_stock(con):
    assert con.execute("SELECT count(*) FROM raw.sales WHERE sale_date >= '2026-10-01'").fetchone()[0] > 0
    assert con.execute("SELECT count(*) FROM raw.stock WHERE snapshot_date >= '2026-10-01'").fetchone()[0] == 0


def test_trap_anomalies(con):
    rows = con.execute(f"SELECT store_id, sale_date FROM raw.sales WHERE qty = {ANOMALY_QTY}").fetchall()
    assert len(rows) == 40
    aug = [r for r in rows if str(r[1]).startswith("2026-08")]
    assert len(aug) == 8 and {r[0] for r in aug} == {ANOMALY_STORE}


def test_returns_present(con):
    share = con.execute("SELECT avg(CASE WHEN qty < 0 THEN 1 ELSE 0 END) FROM raw.sales").fetchone()[0]
    assert 0.01 < share < 0.06


def test_generate_is_deterministic(tmp_path):
    def fingerprint(p):
        c = duckdb.connect(str(p), read_only=True)
        try:
            return c.execute("SELECT count(*), sum(amount), sum(qty) FROM raw.sales").fetchone()
        finally:
            c.close()
    assert fingerprint(generate(tmp_path / "a.duckdb")) == fingerprint(generate(tmp_path / "b.duckdb"))


def test_generate_overwrites_existing_file(tmp_path):
    def counts(path):
        c = duckdb.connect(str(path), read_only=True)
        try:
            return [c.execute(f"SELECT count(*) FROM raw.{t}").fetchone()[0]
                    for t in ("products", "sales", "stock", "stores")]
        finally:
            c.close()

    fresh = counts(generate(tmp_path / "fresh.duckdb"))
    p = tmp_path / "x.duckdb"
    generate(p, seed=7)  # другое содержимое под тем же именем
    generate(p)  # перезапись: не падает на существующей схеме raw
    assert counts(p) == fresh
