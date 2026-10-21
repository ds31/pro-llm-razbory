import json
from types import SimpleNamespace as NS

import pytest

from conftest import ROOT
from razbor03.cli import main
from razbor03.experiment import (PLAN, RunSpec, empty_store, execute, import_01, save_store, summarize,
                                 total_cost)
from razbor03.runs import Answer
from razbor03.scenarios import open_scenario
from razbor03.spec import load_suite

SUITE = load_suite(ROOT / "eval" / "questions.yaml")


class OracleAgent:
    """Отвечает живым эталоном своего сценария; на вопросах из `wrong` ошибается в 2 раза."""

    def __init__(self, con, wrong=()):
        self.answers = {q.question: float(con.execute(q.check_sql).fetchone()[0]) for q in SUITE.questions}
        self.ids = {q.question: q.id for q in SUITE.questions}
        self.wrong = set(wrong)

    def answer(self, question):
        v = self.answers[question]
        if self.ids[question] in self.wrong:
            v *= 2
        return Answer("", v, "", "эталон", [], cost_usd=0.01)


def factory(wrong_by_scenario):
    def make(*, con, catalog, variant, model, client):
        return OracleAgent(con, wrong_by_scenario.get((variant, str(catalog.closed_through)), ()))
    return make


class Judge:
    """Судья, который всегда говорит «верно»."""

    def __init__(self):
        self.messages = NS(create=lambda **kw: NS(
            content=[NS(type="tool_use", id="j", name="verdict", input={"correct": True, "reason": "похоже на правду"})],
            stop_reason="tool_use", usage=NS(input_tokens=1000, output_tokens=50)))


@pytest.fixture(scope="module")
def store(data_dir):
    st = empty_store()
    plan = [RunSpec("base-A-1", "base", "A"), RunSpec("base-B-1", "base", "B"), RunSpec("base-B-2", "base", "B"),
            RunSpec("no-anomaly-rule-B", "no-anomaly-rule", "B", tag="anomaly"),
            RunSpec("reload-B", "reload", "B", tag="open_month"),
            RunSpec("reload-stale-B", "reload-stale", "B", tag="open_month")]
    wrong = {("A", "2026-09-30"): {"Q15", "Q16"}}
    execute(st, SUITE, data_dir, Judge(), plan=plan, judges=("anthropic/claude-haiku-5.5",), log=lambda *_: None,
            factory=factory(wrong))
    return st


def test_execute_fills_store_and_skips_done(store, data_dir):
    assert set(store["runs"]) == {"base-A-1", "base-B-1", "base-B-2", "no-anomaly-rule-B", "reload-B", "reload-stale-B"}
    assert set(store["judge"]["anthropic/claude-haiku-5.5"]) == {"base-A-1", "base-B-1"}
    before = json.dumps(store, sort_keys=True)
    execute(store, SUITE, data_dir, Judge(), plan=[RunSpec("base-A-1", "base", "A")], judges=(),
            log=lambda *_: None, factory=None)
    assert json.dumps(store, sort_keys=True) == before


def test_budget_stop(data_dir):
    st = empty_store()
    logs = []
    execute(st, SUITE, data_dir, Judge(), plan=[RunSpec("x", "base", "B", tag="anomaly"), RunSpec("y", "base", "B")],
            judges=(), log=logs.append, factory=factory({}), max_usd=0.05)
    assert list(st["runs"]) == ["x"] and any("бюджет" in m for m in logs)


def test_summary_shows_what_each_checker_misses(store, data_dir):
    s = summarize(store, SUITE, data_dir)
    assert s["checkers"]["live"]["errors"] == 2
    assert s["checkers"]["anthropic/claude-haiku-5.5"]["missed"] == ["base-A-1:Q15", "base-A-1:Q16"]
    # Оракул на дозагруженных данных отвечает октябрём: замороженное число отвергает верные ответы
    d = s["drift"]["reload-B"]
    assert d["live_correct"] == 6 and len(d["frozen"]["rejected"]) == 5 and d["frozen"]["missed"] == []
    assert d["dated_sql"]["rejected"] == d["frozen"]["rejected"]


def test_summary_gate_and_stability(store, data_dir):
    s = summarize(store, SUITE, data_dir)
    assert s["stability"]["B"]["pass_hat_k"] == 1.0 and s["stability"]["A"]["never"] == ["Q15", "Q16"]
    assert s["gate"]["no-change"]["exit_code"] == 0
    # оракул сценария считает по raw, поэтому поломка витрин его не задевает — регрессий нет
    assert s["gate"]["no-anomaly-rule"]["exit_code"] == 0


def test_total_cost_skips_imported_runs():
    st = empty_store()
    st["runs"]["base-A-1"] = {"name": "base-A-1", "meta": {"source": "01"}, "answers": [{"cost_usd": 5.0}]}
    st["runs"]["r"] = {"name": "r", "meta": {}, "answers": [{"cost_usd": 0.25}]}
    st["judge"] = {"m": {"r": {"Q01": {"correct": True, "expected": None, "note": "", "cost_usd": 0.5}}}}
    assert total_cost(st) == 0.75


def test_import_01(tmp_path):
    row = {"qid": "Q01", "variant": "A", "got": 1.0, "cost_usd": 0.02, "seconds": 3.0, "stop": "final_answer",
           "run": {"unit": "₽", "explanation": "e", "trace": [{"name": "run_sql", "input": {"sql": "SELECT 1"},
                                                               "output": "1", "is_error": False}]}}
    p = tmp_path / "results.jsonl"
    p.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    (run,) = import_01(p)
    assert run.name == "base-A-1" and run.meta["scenario"] == "base" and run.answers[0].trace[0]["output"] == "1"


def test_cli_offline_all_and_gate(store, data_dir, tmp_path, capsys):
    """Офлайн: сводка пересчитывается по сохранённым ответам; ворота отдают код выхода."""
    root = tmp_path / "pkg"
    (root / "eval").mkdir(parents=True)
    (root / "eval" / "questions.yaml").write_text((ROOT / "eval" / "questions.yaml").read_text(encoding="utf-8"),
                                                  encoding="utf-8")
    (root / "data").symlink_to(data_dir)
    st = json.loads(json.dumps(store))
    from razbor03.cli import _public
    st["summary"] = _public(summarize(st, SUITE, data_dir))
    save_store(st, root / "eval" / "reference-run.json")
    assert main(["--root", str(root), "all", "--offline"]) == 0
    assert "совпадает" in capsys.readouterr().out and (root / "eval" / "out" / "report.html").exists()
    html = (root / "eval" / "out" / "report.html").read_text(encoding="utf-8")
    assert "Живой эталон и судьи" in html and "Записанное число" in html and str(tmp_path) not in html
    assert main(["--root", str(root), "compare", "--old", "ref:base-B-1", "--new", "ref:base-B-2"]) == 0
    assert main(["--root", str(root), "compare", "--old", "ref:base-B-1", "--new", "ref:base-A-1"]) == 1
    assert main(["--root", str(root), "refs"]) == 0
    assert main(["--root", str(root), "check", "ref:reload-stale-B"]) == 0
    assert "reload-stale-B: верно 6 из 6 (live)" in capsys.readouterr().out  # оракул считает по raw сценария


def test_plan_is_what_the_article_counts():
    assert [p.name for p in PLAN][:2] == ["base-A-1", "base-B-1"]
    assert {p.name for p in PLAN} >= {"base-A-3", "base-B-3", "no-anomaly-rule-B", "reload-B", "reload-stale-B"}


def test_direct_api_model_names():
    from razbor03.cli import _direct
    assert _direct("anthropic/claude-haiku-5.5") == "claude-haiku-5-5"
    from razbor03.agent import PRICES
    assert {"claude-haiku-5-5", "claude-sonnet-5-5", "anthropic/claude-haiku-5.5"} <= set(PRICES)
