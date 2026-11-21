from razbor06.discovery import load_discovery
from razbor06.scaffold import dump_acceptance, load_acceptance, scaffold
from conftest import EXAMPLES


def test_filled_example_gives_seven_complete_cases(filled):
    cases = scaffold(filled)
    assert [c.id for c in cases] == ["M1-1", "M1-2", "M1-3", "M1-4", "M2-1", "M2-2", "M3-1"]
    assert all(not c.todo for c in cases)
    assert all(c.signed_by for c in cases)


def test_breakdown_becomes_table_case(filled):
    base = scaffold(filled)[0]
    assert base.kind == "table" and base.covers == ["base"]
    assert base.question == "Какая выручка за сентябрь по магазинам?"
    assert base.row_question.startswith("Какая выручка магазина №{key}")
    assert base.metric_query == {"metric": "revenue", "date_from": "2026-09-01", "date_to": "2026-09-30",
                                 "group_by": ["store_id"]}


def test_check_inherits_owner_signature_and_tolerance(filled):
    c = scaffold(filled)[1]
    assert c.covers == ["issue:anomaly"] and c.kind == "scalar"
    assert c.signed_by == "Финансовый директор" and c.tolerance_pct == 0.5
    assert c.metric_query["filters"] == {"store_id": [2]}


def test_base_case_uses_eval_wording_and_ratio(filled):
    m3 = scaffold(filled)[-1]
    assert m3.question.startswith("Какую долю валовых продаж составили возвраты")
    assert m3.covers == ["base", "issue:returns", "issue:anomaly"]
    assert m3.metric_query["metric"] == "returns_amount / gross_sales" and m3.metric_query["scale"] == 100


def test_uncovered_issue_becomes_todo_case(filled):
    m1 = filled["questions"][0]
    m1["checks"] = [c for c in m1["checks"] if "issue:anomaly" not in c["covers"]]
    todo = [c for c in scaffold(filled) if c.todo]
    assert len(todo) == 1
    t = todo[0]
    assert t.covers == ["issue:anomaly"] and t.question is None and "9999" in t.hint
    assert {"вопрос-проба", "metric_query", "эталон"} <= set(t.todo)


def test_day1_scaffold_is_skeleton_with_todo():
    cases = scaffold(load_discovery(EXAMPLES / "discovery-day1.yaml"))
    assert [c.id for c in cases] == ["M1-1", "M2-1", "M3-1"]
    for c in cases:
        assert "эталон" in c.todo and "владелец" in c.todo


def test_acceptance_roundtrip(filled, tmp_path):
    cases = scaffold(filled)
    p = tmp_path / "acceptance.yaml"
    p.write_text(dump_acceptance(cases, filled), encoding="utf-8")
    assert load_acceptance(p) == cases


def test_committed_example_is_in_sync(filled):
    """examples/retail/acceptance.yaml — вывод scaffold; правят discovery.yaml, а не его."""
    committed = (EXAMPLES / "acceptance.yaml").read_text(encoding="utf-8")
    assert committed == dump_acceptance(scaffold(filled), filled)
