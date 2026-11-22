"""Загрузчик: проверки пакета, замена по области выгрузки, витрины и сверка с эталоном."""
import json
from datetime import timedelta

import pytest

from razbor08.dwh import Warehouse
from razbor08.source import DocFilter, EMPTY_REF, export_time
from razbor08.truth import compare, snapshot

from .conftest import START


@pytest.fixture
def wh():
    w = Warehouse(":memory:")
    yield w
    w.close()


def _full_night(src, wh, tmp_path, day, name="full"):
    t = export_time(day)
    src.export(tmp_path / name, t, DocFilter.all())
    res = wh.load_batch(tmp_path / name)
    wh.build_marts(day)
    return t, res


def _diff(src, wh, tmp_path, t, day):
    snap = snapshot(src, t, day, tmp_path / "truth")
    return compare(wh, snap)


def test_full_load_matches_truth(src, wh, tmp_path):
    day = START - timedelta(days=1)
    t, res = _full_night(src, wh, tmp_path, day)
    assert res.status == "applied"
    d = _diff(src, wh, tmp_path, t, day)
    assert d["sales_days_bad"] == 0 and d["stock_cells_bad"] == 0 and d["month_end_cells_bad"] == 0
    assert d["revenue_abs_err"] == 0 and d["store_months_bad"] == 0
    # витрины совместимы со слоем метрик пакета 01
    cols = [r[0] for r in wh.con.execute("DESCRIBE mart.sales_daily").fetchall()]
    assert cols == ["sale_date", "month", "store_id", "region", "sku", "category", "brand",
                    "net_qty", "net_amount", "return_amount"]
    cols = [r[0] for r in wh.con.execute("DESCRIBE mart.stock_month_end").fetchall()]
    assert cols == ["month_end", "month", "store_id", "region", "sku", "category", "brand", "qty_on_hand"]


def test_compare_sees_missing_change(src, wh, tmp_path):
    day = START - timedelta(days=1)
    _full_night(src, wh, tmp_path, day)
    src.advance(START)                       # в источнике правки, в хранилище — нет
    t = export_time(START)
    wh.build_marts(START)
    d = _diff(src, wh, tmp_path, t, START)
    assert d["sales_days_bad"] > 0


def _rewrite(path, fn):
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(fn(lines)) + "\n", encoding="utf-8")


def test_k1_truncated_file_rejects_batch(src, wh, tmp_path):
    day = START - timedelta(days=1)
    _full_night(src, wh, tmp_path, day)
    before = wh.con.execute("SELECT count(*) FROM raw.docs").fetchone()[0]
    src.advance(START)
    t = export_time(START)
    src.export(tmp_path / "n1", t, DocFilter.all())
    _rewrite(tmp_path / "n1" / "Document_РозничныеПродажи.json", lambda ls: ls[:-1])
    res = wh.load_batch(tmp_path / "n1")
    assert res.status == "rejected"
    assert any(c["id"] == "K1" and not c["ok"] for c in res.checks)
    assert wh.con.execute("SELECT count(*) FROM raw.docs").fetchone()[0] == before
    assert wh.con.execute("SELECT status FROM meta.loads ORDER BY batch_id DESC LIMIT 1").fetchone()[0] == "rejected"


def test_k2_duplicate_ref_rejects_batch(src, wh, tmp_path):
    t = export_time(START - timedelta(days=1))
    src.export(tmp_path / "b", t, DocFilter.all())
    _rewrite(tmp_path / "b" / "Catalog_Номенклатура.json", lambda ls: ls + [ls[0]])
    man = json.loads((tmp_path / "b" / "manifest.json").read_text(encoding="utf-8"))
    man["objects"]["Catalog_Номенклатура"]["count"] += 1     # полнота сходится, ключ — нет
    (tmp_path / "b" / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    res = wh.load_batch(tmp_path / "b")
    assert res.status == "rejected"
    assert [c["id"] for c in res.checks if not c["ok"]] == ["K2"]


def test_k3_unknown_product_holds_document(src, wh, tmp_path):
    t = export_time(START - timedelta(days=1))
    src.export(tmp_path / "b", t, DocFilter.all())
    path = tmp_path / "b" / "Document_РозничныеПродажи.json"

    def broke(ls):
        doc = json.loads(ls[0])
        doc["Товары"][0]["Номенклатура_Key"] = EMPTY_REF
        return [json.dumps(doc, ensure_ascii=False)] + ls[1:]
    _rewrite(path, broke)
    res = wh.load_batch(tmp_path / "b")
    assert res.status == "applied"
    assert len(res.held) == 1
    held = res.held[0]
    assert wh.con.execute("SELECT count(*) FROM raw.docs WHERE ref = ?", [held]).fetchone()[0] == 0
    assert wh.con.execute("SELECT count(*) FROM raw.moves WHERE recorder = ?", [held]).fetchone()[0] == 0
    assert wh.con.execute("SELECT check_id FROM meta.held").fetchone()[0] == "K3"


def test_changed_since_upserts_and_replaces_moves(src, wh, tmp_path):
    day = START - timedelta(days=1)
    _full_night(src, wh, tmp_path, day)
    src.advance(START)
    t = export_time(START)
    src.export(tmp_path / "inc", t, DocFilter.changed_since(export_time(day) - timedelta(hours=2)))
    res = wh.load_batch(tmp_path / "inc")
    assert res.status == "applied"
    wh.build_marts(START)
    d = _diff(src, wh, tmp_path, t, START)
    # прямое удаление в первый день не происходит, поздние записи ещё не видны — расхождений нет
    assert d["sales_days_bad"] == 0 and d["stock_cells_bad"] == 0
    dup = wh.con.execute("SELECT count(*) - count(DISTINCT ref) FROM raw.docs").fetchone()[0]
    assert dup == 0


def test_store_months_scope_removes_deleted(src, wh, tmp_path):
    day = START - timedelta(days=1)
    _full_night(src, wh, tmp_path, day)
    victim, store_ref, month = src.con.execute("""
        SELECT ref, store_ref, date_trunc('month', doc_date)::DATE FROM ib.docs
        WHERE doc_type = 'РозничныеПродажи' ORDER BY ref LIMIT 1""").fetchone()
    for t_, col in (("ib.moves", "recorder"), ("ib.doc_lines", "doc_ref"), ("ib.docs", "ref")):
        src.con.execute(f"DELETE FROM {t_} WHERE {col} = ?", [victim])
    t = export_time(day) + timedelta(hours=1)
    src.export(tmp_path / "sm", t, DocFilter.store_months([(store_ref, month)]))
    wh.load_batch(tmp_path / "sm")
    assert wh.con.execute("SELECT count(*) FROM raw.docs WHERE ref = ?", [victim]).fetchone()[0] == 0
    wh.build_marts(day)
    assert _diff(src, wh, tmp_path, t, day)["sales_days_bad"] == 0


def test_control_totals_match_source(src, wh, tmp_path):
    day = START - timedelta(days=1)
    t, _ = _full_night(src, wh, tmp_path, day)
    a = {(r["store_ref"], r["month"]): (r["docs"], r["qty"], r["amount"]) for r in src.control_totals(t)}
    b = {(r["store_ref"], r["month"]): (r["docs"], r["qty"], r["amount"]) for r in wh.control_totals()}
    assert a == b
