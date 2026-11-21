import json

import duckdb
import pytest
from razbor01.metrics import load_catalog

from razbor06.accept import evaluate, golden_value, layer_value
from razbor06.answers import Answer, load_recorded
from razbor06.paths import PKG01
from razbor06.scaffold import scaffold

WORKS = {"tolerance_pct": 0.5, "every_case_answered": True, "max_cost_usd": 0.05, "max_seconds": 15}


@pytest.fixture(scope="module")
def con(db):
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(PKG01 / "metrics.yaml")


@pytest.fixture(scope="module")
def recorded():
    return load_recorded(PKG01)


@pytest.fixture
def cases(filled):
    return scaffold(filled)


def by_id(cases, cid):
    return next(c for c in cases if c.id == cid)


def test_table_golden_has_row_per_store(con, cases):
    g = golden_value(con, by_id(cases, "M1-1"))
    assert sorted(g) == list(range(1, 13))
    ref = json.loads((PKG01 / "eval" / "reference-run.json").read_text(encoding="utf-8"))
    q19 = next(a for a in ref["answers"] if a["qid"] == "Q19")   # выручка сети за сентябрь
    assert sum(g.values()) == pytest.approx(q19["expected"], abs=0.01)


def test_goldens_equal_recorded_expected(con, cases, recorded):
    """Кейсы с записанным ответом агента стоят на тех же эталонах, что и прогон пакета 01."""
    matched = 0
    for c in cases:
        a = recorded.get(("B", c.question))
        if a is None:
            continue
        matched += 1
        assert golden_value(con, c) == pytest.approx(a.expected, rel=1e-9), c.id
    assert matched == 6


def test_layer_matches_golden_for_all_cases(con, catalog, cases):
    for c in cases:
        exp, got = golden_value(con, c), layer_value(con, catalog, c)
        if c.kind == "table":
            assert got.keys() == exp.keys()
            for k in exp:
                assert got[k] == pytest.approx(exp[k], rel=1e-6), (c.id, k)
        else:
            assert got == pytest.approx(exp, rel=1e-6), c.id


def test_variant_b_waits_only_for_store_rows(con, catalog, cases, recorded):
    v = evaluate(con, catalog, cases, recorded, "B", layer=True, works_when=WORKS)
    assert v.gates["G3"].status == "пройдены"
    assert v.gates["G4"].status == "ждёт прогона"
    assert len(v.waiting) == 12 and all(w.case_id == "M1-1" for w in v.waiting)
    assert v.failed == []
    assert v.verdict == "ждёт прогона"


def test_variant_a_is_rejected_on_three_cases(con, catalog, cases, recorded):
    v = evaluate(con, catalog, cases, recorded, "A", layer=False, works_when=WORKS)
    assert v.gates["G3"].status == "не применимо"
    assert v.gates["G4"].status == "не пройдены"
    assert sorted(v.failed) == ["M1-2", "M1-3", "M3-1"]
    assert v.verdict == "не принят"


def _rows_answers(con, case, variant, factor=1.0):
    g = golden_value(con, case)
    return {(variant, case.row_question.format(key=k)): Answer(v * factor, 0.016, 5.0, "test", v) for k, v in g.items()}


def test_b_accepted_when_store_rows_answered(con, catalog, cases, recorded):
    answers = {**recorded, **_rows_answers(con, by_id(cases, "M1-1"), "B")}
    v = evaluate(con, catalog, cases, answers, "B", layer=True, works_when=WORKS)
    assert v.verdict == "принят" and v.waiting == []


def test_one_wrong_row_fails_table_case(con, catalog, cases, recorded):
    case = by_id(cases, "M1-1")
    rows = _rows_answers(con, case, "B")
    key = ("B", case.row_question.format(key=4))
    rows[key] = Answer(rows[key].value * 1.02, 0.016, 5.0, "test", rows[key].value)
    v = evaluate(con, catalog, cases, {**recorded, **rows}, "B", layer=True, works_when=WORKS)
    assert v.failed == ["M1-1"] and v.verdict == "не принят"


def test_todo_case_blocks_acceptance(con, catalog, filled, recorded):
    m1 = filled["questions"][0]
    m1["checks"] = [c for c in m1["checks"] if "issue:anomaly" not in c["covers"]]
    v = evaluate(con, catalog, scaffold(filled), recorded, "B", layer=True, works_when=WORKS)
    assert v.gates["G1"].status == "не пройдены" and v.verdict == "не принят"


def test_broken_golden_fails_g2(con, catalog, cases, recorded):
    by_id(cases, "M2-2").golden_sql = "SELECT sum(qty_on_hand) FROM raw.stock WHERE snapshot_date = '2030-01-31'"
    v = evaluate(con, catalog, cases, recorded, "B", layer=True, works_when=WORKS)
    assert v.gates["G2"].status == "не пройдены"


def test_layer_mismatch_fails_g3(con, catalog, cases, recorded):
    by_id(cases, "M1-2").metric_query["metric"] = "gross_sales"   # слой считает не то, что подписано
    v = evaluate(con, catalog, cases, recorded, "B", layer=True, works_when=WORKS)
    assert v.gates["G3"].status == "не пройдены" and "M1-2" in v.gates["G3"].detail


def test_cost_limit_fails_g5(con, catalog, cases, recorded):
    v = evaluate(con, catalog, cases, recorded, "B", layer=True, works_when={**WORKS, "max_cost_usd": 0.01})
    assert v.gates["G5"].status == "не пройдены"


def test_answer_counts_and_means(con, catalog, cases, recorded):
    v = evaluate(con, catalog, cases, recorded, "B", layer=True, works_when=WORKS)
    assert v.answered == 6 and v.correct == 6
    assert 0 < v.cost_usd_mean < 0.05 and 0 < v.seconds_mean < 15
