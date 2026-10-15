import json

import duckdb
import pytest

from conftest import ROOT
from razbor01.metrics import load_catalog
from razbor01.tools import make_toolbox, open_db


@pytest.fixture(scope="module")
def box_a(con):
    return make_toolbox("A", con)


@pytest.fixture(scope="module")
def box_b(con):
    return make_toolbox("B", con, load_catalog(ROOT / "metrics.yaml"))


def test_variant_a_sees_only_raw(box_a):
    out, err = box_a.call("list_tables", {})
    assert not err and {t["table"] for t in json.loads(out)} == {"raw.products", "raw.sales", "raw.stock", "raw.stores"}
    out, err = box_a.call("describe_table", {"table": "raw.sales"})
    assert not err and "amount" in out
    out, err = box_a.call("run_sql", {"sql": "SELECT count(*) AS n FROM raw.stores"})
    assert (json.loads(out), err) == ([{"n": 12}], False)
    assert box_a.call("run_sql", {"sql": "SELECT * FROM mart.sales_daily"})[1] is True
    assert box_a.call("query_metric", {"metric_id": "revenue"})[1] is True


def test_variant_b_metrics_and_rules(box_b):
    listing = json.loads(box_b.call("list_metrics", {})[0])
    assert listing["closed_through"] == "2026-09-30" and len(listing["rules"]) == 5
    out, err = box_b.call("query_metric", {"metric_id": "revenue", "date_from": "2026-09-01",
                                           "date_to": "2026-09-30", "filters": {"category": ["Напитки"]}})
    data = json.loads(out)
    assert not err and data["sql"].startswith("SELECT") and data["rows"][0]["value"] > 0


def test_variant_b_errors_are_hints_not_crashes(box_b):
    out, err = box_b.call("query_metric", {"metric_id": "revenue", "date_from": "2026-10-01", "date_to": "2026-10-31"})
    assert err and "незакрытый" in out
    out, err = box_b.call("run_sql", {"sql": "SELECT sum(amount) FROM raw.sales"})
    assert err and "mart.*" in out
    out, err = box_b.call("query_metric", {"metric_id": "revenue", "date_from": "вчера", "date_to": "2026-09-30"})
    assert err
    out, err = box_b.call("describe_metric", {})
    assert err


def test_empty_filter_and_duplicate_group_by_are_hints(box_b):
    base = {"metric_id": "revenue", "date_from": "2026-09-01", "date_to": "2026-09-30"}
    out, err = box_b.call("query_metric", {**base, "filters": {"region": []}})
    assert err and "пуст" in out and "IN ()" not in out
    out, err = box_b.call("query_metric", {**base, "group_by": ["region", "region"]})
    assert err and "повтор" in out


def test_read_only_connection_blocks_writes_even_past_guard(db_path):
    c = open_db(db_path)
    with pytest.raises(duckdb.Error):
        c.execute("DELETE FROM raw.sales")
    c.close()


@pytest.mark.parametrize("variant, sql", [
    ("A", "SELECT * FROM read_text('{f}')"),
    ("A", "SELECT * FROM read_csv('{f}')"),
    ("B", "SELECT * FROM read_text('{f}')"),
])
def test_agent_cannot_read_files(db_path, tmp_path, variant, sql):
    secret = tmp_path / "fake.env"
    secret.write_text("API_KEY=sk-secret-123\n", encoding="utf-8")
    c = open_db(db_path)
    try:
        box = make_toolbox(variant, c, load_catalog(ROOT / "metrics.yaml") if variant == "B" else None)
        out, err = box.call("run_sql", {"sql": sql.format(f=secret)})
        assert err and "sk-secret-123" not in out
    finally:
        c.close()


def test_truncation_is_explicit(box_a):
    out, err = box_a.call("run_sql", {"sql": "SELECT sale_date, sum(amount) AS s FROM raw.sales GROUP BY 1"})
    data = json.loads(out)
    assert not err and data["truncated"] is True and len(data["rows"]) == 50 and "агрегируйте" in data["hint"]
    out, _ = box_a.call("run_sql", {"sql": "SELECT * FROM raw.stores"})
    assert isinstance(json.loads(out), list)


def test_query_metric_truncated_flag(box_b):
    base = {"metric_id": "revenue", "date_from": "2026-01-01", "date_to": "2026-09-30"}
    small = json.loads(box_b.call("query_metric", base)[0])
    assert small["truncated"] is False
    big = json.loads(box_b.call("query_metric", {**base, "group_by": ["store_id", "month"]})[0])
    assert big["truncated"] is True and len(big["rows"]) == 50


def test_nested_decimal_serializes(box_a):
    out, err = box_a.call("run_sql", {"sql": "SELECT list(amount) AS xs FROM (SELECT amount FROM raw.sales LIMIT 3)"})
    assert not err and len(json.loads(out)[0]["xs"]) == 3
