from types import SimpleNamespace as NS

import pytest

from razbor01.agent import PRICES, run_agent
from razbor01.tools import make_toolbox


class FakeClient:
    """Отдаёт заранее заготовленные ответы модели и запоминает запросы."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        return self.script.pop(0)


def tool_use(i, name, args):
    return NS(type="tool_use", id=i, name=name, input=args)


def reply(blocks, stop="tool_use", tin=1000, tout=100):
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=tin, output_tokens=tout))


@pytest.fixture(scope="module")
def box(con):
    return make_toolbox("A", con)


def test_tool_then_final_answer(box):
    client = FakeClient([
        reply([tool_use("t1", "run_sql", {"sql": "SELECT 12 AS n"})]),
        reply([tool_use("t2", "final_answer", {"value": 12, "unit": "шт.", "explanation": "посчитал"})]),
    ])
    run = run_agent("Сколько магазинов?", box, client)
    assert run.value == 12.0 and run.stop == "final_answer"
    assert [c.name for c in run.trace] == ["run_sql", "final_answer"]
    assert (run.input_tokens, run.output_tokens) == (2000, 200)
    sent = client.calls[1]["messages"]
    assert sent[-1]["role"] == "user" and sent[-1]["content"][0]["tool_use_id"] == "t1"
    assert client.calls[0]["model"] == "claude-sonnet-5-5"
    assert client.calls[0]["tools"] == box.specs and client.calls[0]["system"] == box.system


def test_tool_error_goes_back_to_model(box):
    client = FakeClient([
        reply([tool_use("t1", "run_sql", {"sql": "DROP TABLE raw.sales"})]),
        reply([tool_use("t2", "final_answer", {"value": 1, "unit": "", "explanation": ""})]),
    ])
    run = run_agent("q", box, client)
    assert run.trace[0].is_error
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_cost_uses_model_price(box):
    client = FakeClient([reply([tool_use("t", "final_answer", {"value": 1, "unit": "", "explanation": ""})],
                               tin=1_000_000, tout=100_000)])
    run = run_agent("q", box, client)
    pin, pout = PRICES["claude-sonnet-5-5"]
    assert run.cost_usd("claude-sonnet-5-5") == pytest.approx(pin + pout / 10)


@pytest.mark.parametrize("script, stop", [
    ([reply([NS(type="text", text="не знаю")], stop="end_turn")], "no_answer"),
    ([reply([], stop="refusal")], "refusal"),
    ([reply([tool_use("t", "final_answer", {"value": "около ста", "unit": "", "explanation": ""})])], "bad_answer"),
])
def test_runs_without_number_are_marked(box, script, stop):
    run = run_agent("q", box, FakeClient(script))
    assert run.value is None and run.stop == stop


def test_max_turns(box):
    script = [reply([tool_use(f"t{i}", "list_tables", {})]) for i in range(3)]
    run = run_agent("q", box, FakeClient(script), max_turns=3)
    assert run.stop == "max_turns" and len(run.trace) == 3


def test_nonfinite_value_is_bad_answer(box):
    from types import SimpleNamespace as NS
    from razbor01.agent import run_agent
    for bad in (float("nan"), float("inf"), float("-inf")):
        block = NS(type="tool_use", id="t", name="final_answer", input={"value": bad, "unit": "", "explanation": ""})
        client = NS(messages=NS(create=lambda **kw: NS(
            content=[block], stop_reason="tool_use", usage=NS(input_tokens=1, output_tokens=1))))
        run = run_agent("q", box, client)
        assert run.stop == "bad_answer" and run.value is None


def test_huge_int_is_bad_answer(box):
    from types import SimpleNamespace as NS
    from razbor01.agent import run_agent
    block = NS(type="tool_use", id="t", name="final_answer", input={"value": 10**400, "unit": "", "explanation": ""})
    client = NS(messages=NS(create=lambda **kw: NS(
        content=[block], stop_reason="tool_use", usage=NS(input_tokens=1, output_tokens=1))))
    assert run_agent("q", box, client).stop == "bad_answer"


def test_openrouter_model_ids_priced_as_anthropic():
    """Через OpenRouter (ANTHROPIC_BASE_URL=https://openrouter.ai/api) модель зовётся anthropic/…;
    цена та же, что у Anthropic, — отчёт считает её одинаково при любом шлюзе."""
    assert PRICES["anthropic/claude-sonnet-5.5"] == PRICES["claude-sonnet-5-5"]
    assert PRICES["anthropic/claude-opus-5.5"] == PRICES["claude-opus-5-5"]
    assert PRICES["anthropic/claude-haiku-5.5"] == PRICES["claude-haiku-5-5"]
