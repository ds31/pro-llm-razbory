from types import SimpleNamespace as NS

import pytest

from conftest import ROOT
from razbor01.agent import AgentRun, ToolCall
from razbor01.golden import load_questions
from razbor01.metrics import load_catalog
from razbor01.offline import OracleClient
from razbor01.report import PASS_MIN_B, render_report
from razbor01.runner import QuestionResult, run_eval, save_jsonl, summarize

QUESTIONS = load_questions(ROOT / "eval" / "questions.yaml")


@pytest.fixture(scope="module")
def results(con):
    return run_eval(con, load_catalog(ROOT / "metrics.yaml"), QUESTIONS[:4], OracleClient(con, QUESTIONS[:4]))


def test_eval_runs_both_variants(results):
    assert [(r.qid, r.variant) for r in results][:2] == [("Q01", "A"), ("Q02", "A")]
    assert len(results) == 8 and all(r.correct for r in results)


def test_summary_counts(results):
    s = summarize(results)
    assert s["A"]["correct"] == 4 and s["B"]["accuracy_pct"] == 100.0
    assert s["B"]["by_trap"]["none"] == "4/4"


def test_api_failure_on_one_question_does_not_stop_run(con):
    class Boom:
        messages = NS(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("rate limit")))
    rs = run_eval(con, load_catalog(ROOT / "metrics.yaml"), QUESTIONS[:2], Boom(), variants=("B",))
    assert len(rs) == 2 and all(not r.correct and r.stop.startswith("error") for r in rs)


def test_api_failure_keeps_known_trace_and_tokens(con):
    """Первый ход прошёл (инструмент, токены), второй упал: известное не теряется."""
    calls = []

    def create(**kw):
        calls.append(kw)
        if len(calls) == 2:
            raise TypeError("create() got an unexpected keyword argument 'output_config'")
        block = NS(type="tool_use", id="t1", name="list_metrics", input={})
        return NS(content=[block], stop_reason="tool_use", usage=NS(input_tokens=100, output_tokens=20))
    rs = run_eval(con, load_catalog(ROOT / "metrics.yaml"), QUESTIONS[:1], NS(messages=NS(create=create)),
                  variants=("B",))
    r = rs[0]
    assert r.stop == "error: TypeError: create() got an unexpected keyword argument 'output_config'"
    assert [c.name for c in r.run.trace] == ["list_metrics"]
    assert r.run.input_tokens == 100 and r.cost_usd > 0


def test_nonfinite_answer_is_bad_answer(con):
    for bad in (float("nan"), float("inf")):
        block = NS(type="tool_use", id="t", name="final_answer", input={"value": bad, "unit": "", "explanation": ""})
        client = NS(messages=NS(create=lambda **kw: NS(
            content=[block], stop_reason="tool_use", usage=NS(input_tokens=1, output_tokens=1))))
        r = run_eval(con, load_catalog(ROOT / "metrics.yaml"), QUESTIONS[:1], client, variants=("B",))[0]
        assert r.stop == "bad_answer" and not r.correct


def test_paths_and_user_name_do_not_leak(con, tmp_path):
    leak = "IO Error: Cannot open /home/secretuser/work/x/data/retail.duckdb and /Users/bob/y"

    class Leaky:
        messages = NS(create=lambda **kw: (_ for _ in ()).throw(RuntimeError(leak)))
    rs = run_eval(con, load_catalog(ROOT / "metrics.yaml"), QUESTIONS[:1], Leaky(), variants=("B",))
    rs[0].run.trace.append(ToolCall("run_sql", {"sql": "x"}, "Ошибка: /home/secretuser/a.csv", True))
    p = save_jsonl(rs, tmp_path / "r.jsonl")
    html = render_report(rs, summarize(rs), {})
    assert "secretuser" not in p.read_text(encoding="utf-8") and "secretuser" not in html
    assert "bob" not in html and "~" in rs[0].stop


def test_report_html(results):
    html = render_report(results, summarize(results), {"модель": "офлайн-эталон"})
    assert html.startswith("<!doctype html>") and 'name="viewport"' in html
    assert 'id="trace-Q01-B"' in html and 'id="summary"' in html and 'id="traps"' in html
    assert f"B ≥ {PASS_MIN_B}/30" in html


def test_report_escapes_agent_text(results):
    r = results[0]
    r.run.explanation = "<script>alert(1)</script>"
    r.stop = "error: <img src=x onerror=1>"
    html = render_report(results, summarize(results), {})
    assert "<script>alert(1)</script>" not in html and "<img src=x" not in html


def _fake(got, expected=100.0, trap_value=150.0, trap="dup_join"):
    return QuestionResult("Q99", trap, "вопрос", "A", expected, got, False, 0.0, 0.0, "final_answer",
                          AgentRun(value=got), trap_value=trap_value)


def test_report_marks_trap_hit():
    hit, miss = _fake(150.0), _fake(7.0)
    html = render_report([hit], summarize([hit]), {})
    assert "попал в ловушку" in html and "дубли в справочнике" in html.split("попал в ловушку")[1][:60]
    miss_html = render_report([miss], summarize([miss]), {})
    assert "попал в ловушку" not in miss_html


def test_trap_hit_only_for_wrong_answers():
    ok = _fake(100.0)
    ok.correct = True
    assert "попал в ловушку" not in render_report([ok], summarize([ok]), {})
