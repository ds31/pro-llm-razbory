from types import SimpleNamespace as NS

import pytest

from conftest import ROOT
from razbor03.agent import load_factory, make, price
from razbor03.runs import Answer, Run, clip_trace, load_run, run_suite, save_run
from razbor03.scenarios import open_scenario
from razbor03.spec import load_suite

SUITE = load_suite(ROOT / "eval" / "questions.yaml")


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


def tool_use(i, name, args):
    return NS(type="tool_use", id=i, name=name, input=args)


def reply(blocks, tin=1000, tout=100):
    return NS(content=blocks, stop_reason="tool_use", usage=NS(input_tokens=tin, output_tokens=tout))


class EchoAgent:
    def __init__(self, values):
        self.values = values

    def answer(self, question):
        v = self.values[question]
        if isinstance(v, Exception):
            raise v
        return Answer(qid="", value=v, explanation=f"см. /home/someone/x.csv", trace=[
            {"name": "run_sql", "input": {"sql": "SELECT 1"}, "output": "x" * 5000}])


def test_run_suite_keeps_order_only_and_scrubs():
    qs = {q.question: 1.0 for q in SUITE.questions}
    run = run_suite(EchoAgent(qs), SUITE, "t", {"agent": "echo"}, only={"Q01", "Q19"})
    assert [a.qid for a in run.answers] == ["Q01", "Q19"]
    assert "/home/someone" not in run.answers[0].explanation
    assert len(run.answers[0].trace[0]["output"]) < 2100 and "обрезано" in run.answers[0].trace[0]["output"]
    assert run.meta["questions"] == 2 and run.meta["agent"] == "echo"


def test_failure_on_one_question_does_not_stop_run():
    qs = {q.question: 1.0 for q in SUITE.questions}
    qs[SUITE.get("Q02").question] = RuntimeError("сеть")
    run = run_suite(EchoAgent(qs), SUITE, "t", {}, only={"Q01", "Q02", "Q03"})
    a = run.by_qid()["Q02"]
    assert a.value is None and a.stop.startswith("error: RuntimeError")
    assert run.by_qid()["Q03"].value == 1.0


def test_run_roundtrip(tmp_path):
    run = Run("r", {"m": 1}, [Answer("Q01", 2.5, "₽", "e", [{"name": "x", "input": {}, "output": "", "is_error": False}])])
    assert load_run(save_run(run, tmp_path / "r.json")).to_dict() == run.to_dict()


def test_demo_agent_wraps_package_01(data_dir):
    con, cat = open_scenario(data_dir, "base")
    try:
        client = FakeClient([
            reply([tool_use("t1", "list_metrics", {})]),
            reply([tool_use("t2", "final_answer", {"value": 42, "unit": "₽", "explanation": "ok", "metric_id": "revenue"})]),
        ])
        agent = load_factory("razbor03.agent:make")(con=con, catalog=cat, variant="B",
                                                     model="anthropic/claude-sonnet-5.5", client=client)
        a = agent.answer("Какая выручка?")
    finally:
        con.close()
    assert a.value == 42.0 and [c["name"] for c in a.trace] == ["list_metrics", "final_answer"]
    assert "closed_through" in a.trace[0]["output"]
    assert a.cost_usd == pytest.approx(price("anthropic/claude-sonnet-5.5", 2000, 200))


def test_load_factory_rejects_bad_spec():
    with pytest.raises(ValueError):
        load_factory("razbor03.agent")
    assert load_factory("razbor03.agent:make") is make


def test_clip_trace_keeps_short_output():
    assert clip_trace([{"name": "a", "input": {"k": 1}, "output": "ok"}])[0] == {
        "name": "a", "input": {"k": 1}, "output": "ok", "is_error": False}
