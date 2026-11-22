"""Синтетическая информационная база 1С: история, события дня, выгрузка в файлы обмена."""
import json
import re
from datetime import timedelta

from razbor08.source import DocFilter, EMPTY_REF, PAGE_OBJECTS, Source1C, export_time

from .conftest import START, TINY

UUID_RX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _q(src, sql, *p):
    return src.con.execute(sql, list(p)).fetchall()


def test_history_shape(src):
    assert _q(src, "SELECT count(*) FROM ib.stores")[0][0] == TINY.stores
    assert _q(src, "SELECT count(*) FROM ib.products")[0][0] == TINY.skus
    # продажи: магазин × день истории; ввод остатков — по одному на магазин
    n_sales = _q(src, "SELECT count(*) FROM ib.docs WHERE doc_type = 'РозничныеПродажи'")[0][0]
    assert n_sales == TINY.stores * TINY.history_days
    assert _q(src, "SELECT count(*) FROM ib.docs WHERE doc_type = 'ВводОстатков'")[0][0] == TINY.stores
    assert _q(src, "SELECT max(doc_date) FROM ib.docs")[0][0] == START - timedelta(days=1)
    # строки продаж: ровно lines на документ, разные товары внутри документа
    bad = _q(src, """SELECT count(*) FROM (SELECT doc_ref, count(*) n, count(DISTINCT product_ref) k
                      FROM ib.doc_lines JOIN ib.docs d ON d.ref = doc_ref
                      WHERE d.doc_type = 'РозничныеПродажи' GROUP BY doc_ref) WHERE n <> ? OR k <> n""",
             TINY.lines)[0][0]
    assert bad == 0
    refs = [r[0] for r in _q(src, "SELECT ref FROM ib.docs LIMIT 50")]
    assert all(UUID_RX.match(r) for r in refs)


def test_moves_follow_posted_docs(src):
    # у каждого проведённого документа движения по каждой строке, у непроведённых — нет
    missing = _q(src, """SELECT count(*) FROM ib.doc_lines l JOIN ib.docs d ON d.ref = l.doc_ref
                          WHERE d.posted AND NOT EXISTS (SELECT 1 FROM ib.moves m
                            WHERE m.recorder = l.doc_ref AND m.line_no = l.line_no)""")[0][0]
    assert missing == 0
    # продажа — расход, возврат (qty < 0) — приход
    kinds = dict(_q(src, """SELECT CASE WHEN l.qty > 0 THEN 'sale' ELSE 'return' END, min(m.record_type)
                            FROM ib.moves m JOIN ib.doc_lines l ON l.doc_ref = m.recorder AND l.line_no = m.line_no
                            JOIN ib.docs d ON d.ref = l.doc_ref WHERE d.doc_type = 'РозничныеПродажи'
                            GROUP BY 1"""))
    assert kinds["sale"] == "Expense"
    assert kinds["return"] == "Receipt"


def test_stock_stays_balanced(src):
    # поступления примерно покрывают продажи: средний остаток не уходит в минус и не растёт кратно
    avg = _q(src, """SELECT avg(b) FROM (SELECT store_ref, product_ref,
                       sum(CASE record_type WHEN 'Receipt' THEN qty ELSE -qty END) AS b
                     FROM ib.moves GROUP BY ALL)""")[0][0]
    assert 50 < avg < 200


def test_deterministic():
    a = Source1C.create(":memory:", TINY, sim_start=START, seed=8)
    b = Source1C.create(":memory:", TINY, sim_start=START, seed=8)
    for s in (a, b):
        s.advance(START)
    qa = a.con.execute("SELECT sum(amount), count(*) FROM ib.doc_lines").fetchall()
    qb = b.con.execute("SELECT sum(amount), count(*) FROM ib.doc_lines").fetchall()
    assert qa == qb
    a.close()
    b.close()


def test_advance_day_events(src):
    ev = src.advance(START)
    assert ev["new_sales"] == TINY.stores
    assert ev["edited"] >= 1 and ev["unposted"] >= 1 and ev["marked"] >= 1 and ev["late"] >= 1
    # правка задним числом: дата документа старая, дата изменения — сегодня
    rows = _q(src, """SELECT doc_date, modified_at, version FROM ib.docs
                      WHERE modified_at::DATE = ? AND doc_date < ? AND posted""", START, START)
    assert rows and all(r[2] >= 2 for r in rows)
    # непроведённый и помеченный на удаление — без движений
    left = _q(src, """SELECT count(*) FROM ib.moves m JOIN ib.docs d ON d.ref = m.recorder
                      WHERE NOT d.posted OR d.deletion_mark""")[0][0]
    assert left == 0


def test_direct_delete_every_third_day(src):
    deleted = 0
    for i in range(3):
        deleted += src.advance(START + timedelta(days=i))["deleted"]
    assert deleted == 1
    orphan = _q(src, "SELECT count(*) FROM ib.doc_lines WHERE doc_ref NOT IN (SELECT ref FROM ib.docs)")[0][0]
    assert orphan == 0


def test_late_docs_invisible_until_commit(src):
    ev = src.advance(START)
    t = export_time(START)
    hidden = _q(src, "SELECT count(*) FROM ib.docs WHERE modified_at < ? AND visible_at > ?", t, t)[0][0]
    assert hidden == ev["late"]


def test_export_full_manifest_and_format(src, tmp_path):
    src.advance(START)
    t = export_time(START)
    m = src.export(tmp_path, t, DocFilter.all())
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert man == m
    docs = man["objects"]["Document_РозничныеПродажи"]
    visible = _q(src, "SELECT count(*) FROM ib.docs WHERE doc_type = 'РозничныеПродажи' AND visible_at <= ?", t)[0][0]
    assert docs["count"] == visible
    first = json.loads((tmp_path / docs["file"]).read_text(encoding="utf-8").splitlines()[0])
    for key in ("Ref_Key", "Number", "Date", "Posted", "DeletionMark", "DataVersion", "ДатаИзменения",
                "Магазин_Key", "Товары"):
        assert key in first
    assert {"LineNumber", "Номенклатура_Key", "Количество", "Сумма"} <= set(first["Товары"][0])
    lines = sum(len(json.loads(x)["Товары"]) for x in (tmp_path / docs["file"]).read_text(encoding="utf-8").splitlines())
    assert lines == docs["lines"]
    # нагрузка на источник: страницы по PAGE_OBJECTS объектов, строки, байты
    assert docs["requests"] == -(-docs["count"] // PAGE_OBJECTS)
    assert m["stats"]["rows"] > 0 and m["stats"]["bytes"] > 0
    assert m["stats"]["requests"] == sum(o["requests"] for o in m["objects"].values())


def test_export_changed_since_and_doc_date(src, tmp_path):
    src.advance(START)
    t = export_time(START)
    m = src.export(tmp_path / "inc", t, DocFilter.changed_since(t - timedelta(days=1)))
    changed = _q(src, "SELECT count(*) FROM ib.docs WHERE modified_at > ? AND visible_at <= ?",
                 t - timedelta(days=1), t)[0][0]
    assert sum(o["count"] for k, o in m["objects"].items() if k.startswith("Document_")) == changed
    m2 = src.export(tmp_path / "dd", t, DocFilter.doc_date(START - timedelta(days=2), START))
    by_date = _q(src, "SELECT count(*) FROM ib.docs WHERE doc_date BETWEEN ? AND ? AND visible_at <= ?",
                 START - timedelta(days=2), START, t)[0][0]
    assert sum(o["count"] for k, o in m2["objects"].items() if k.startswith("Document_")) == by_date
    # справочники выгружаются целиком при любом фильтре
    assert m["objects"]["Catalog_Номенклатура"]["count"] == TINY.skus


def test_empty_ref_for_missing_partner(src, tmp_path):
    t = export_time(START - timedelta(days=1))
    m = src.export(tmp_path, t, DocFilter.all())
    first = json.loads((tmp_path / m["objects"]["Document_РозничныеПродажи"]["file"]).read_text(
        encoding="utf-8").splitlines()[0])
    assert first["Контрагент_Key"] == EMPTY_REF


def test_control_totals_counts_one_request(src):
    src.advance(START)
    before = src.requests
    tot = src.control_totals(export_time(START))
    assert src.requests == before + 1
    assert {"store_ref", "month", "docs", "qty", "amount"} <= set(tot[0])
