import pytest

from razbor01.offline import OracleClient
from razbor04.bench import BenchResult, run_bench, summarize
from razbor04.prices import list_cost

from conftest import CATALOG, QUESTIONS, ScriptClient, reply, tool_use

Q = QUESTIONS[:3]


def oracle_factory(con):
    return lambda model: OracleClient(con, Q)


def test_bench_runs_models_variants_runs(con):
    rs = run_bench(con, CATALOG, Q, oracle_factory(con), models=["m1", "m2"], variants=("A", "B"),
                   runs=(1, 2), priced=False)
    assert len(rs) == 2 * 2 * 2 * 3
    assert {(r.model, r.variant, r.run) for r in rs} == {(m, v, k) for m in ("m1", "m2") for v in "AB" for k in (1, 2)}
    assert all(r.correct and r.stop == "final_answer" for r in rs)


def test_cost_tokens_steps_from_meter(con):
    model = "anthropic/claude-haiku-5.5"
    exp = None

    def factory(m):
        from razbor01.golden import expected_value
        v = expected_value(con, Q[0])
        return ScriptClient([
            reply([tool_use("t1", "list_tables", {})], tin=1000, tout=100, cost=0.0004, thinking=40, cache_read=500),
            reply([tool_use("t2", "final_answer", {"value": v, "unit": "₽", "explanation": "x"})], tin=3000, tout=50,
                  cost=0.0005),
        ])
    (r,) = run_bench(con, CATALOG, Q[:1], factory, models=[model], variants=("A",))
    assert r.correct and r.steps == 2 and r.tools == ["list_tables", "final_answer"]
    assert (r.input_tokens, r.output_tokens, r.thinking_tokens) == (4000, 150, 40)
    assert r.cost_list_usd == pytest.approx(list_cost(model, 4500, 150))
    assert r.cost_billed_usd == pytest.approx(0.0009) and r.cache_read_tokens == 500


def test_api_error_is_not_a_wrong_answer(con):
    rs = run_bench(con, CATALOG, Q[:2], lambda m: ScriptClient([RuntimeError("502"), RuntimeError("502")]),
                   models=["anthropic/claude-haiku-5.5"], variants=("B",))
    assert all(r.api_error and not r.correct for r in rs)
    s = summarize(rs)["anthropic/claude-haiku-5.5"]["B"]
    assert s["api_errors"] == 2 and s["wrong"] == 0 and s["correct"] == 0


def test_wrong_answer_counted_as_wrong(con):
    rs = run_bench(con, CATALOG, Q[:1], lambda m: ScriptClient(
        [reply([tool_use("t", "final_answer", {"value": -1, "unit": "", "explanation": ""})])]),
        models=["anthropic/claude-haiku-5.5"], variants=("A",))
    s = summarize(rs)["anthropic/claude-haiku-5.5"]["A"]
    assert s["wrong"] == 1 and s["api_errors"] == 0 and s["usd_per_correct"] is None


def _r(model, variant, run, correct, cost, sec, trap="none", qid="Q01", stop="final_answer"):
    return BenchResult(model=model, variant=variant, run=run, qid=qid, trap=trap, question="", expected=1.0,
                       got=1.0 if correct else 2.0, correct=correct, stop=stop, steps=2, tools=[],
                       input_tokens=1000, output_tokens=100, thinking_tokens=0, cost_list_usd=cost,
                       cost_billed_usd=cost * 2, seconds=sec)


def test_summary_metrics_and_spread():
    rs = [_r("m", "A", 1, True, 0.01, 2.0, qid="Q01"), _r("m", "A", 1, False, 0.03, 4.0, qid="Q02", trap="anomaly"),
          _r("m", "A", 2, True, 0.01, 2.0, qid="Q01"), _r("m", "A", 2, True, 0.01, 2.0, qid="Q02", trap="anomaly")]
    s = summarize(rs)["m"]["A"]
    assert s["runs"] == 2 and s["n"] == 2
    assert s["correct_by_run"] == [1, 2] and s["correct"] == 1.5
    assert s["list_usd_per_answer"] == pytest.approx(0.015)
    assert s["billed_usd_per_answer"] == pytest.approx(0.03)
    assert s["usd_per_answer"] == pytest.approx(0.03) and s["cost_source"] == "списано"
    assert s["usd_per_correct"] == pytest.approx(0.12 / 3)
    assert s["seconds_per_answer"] == pytest.approx(2.5)
    assert s["by_trap"]["anomaly"] == [0, 1] and s["by_trap_n"]["anomaly"] == 1
    assert s["steps_per_answer"] == 2


def test_money_falls_back_to_list_price_without_billing():
    rs = [_r("m", "B", 1, True, 0.01, 1.0)]
    rs[0].cost_billed_usd = None
    s = summarize(rs)["m"]["B"]
    assert s["usd_per_answer"] == pytest.approx(0.01) and s["cost_source"] == "прайс"
    assert s["billed_usd_per_answer"] is None


def test_budget_stops_paid_run(con):
    rs = run_bench(con, CATALOG, Q, oracle_factory(con), models=["anthropic/claude-haiku-5.5"], variants=("A",),
                   max_usd=0.0)
    assert rs == []
