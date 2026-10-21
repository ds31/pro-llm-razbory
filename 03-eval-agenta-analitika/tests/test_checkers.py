from types import SimpleNamespace as NS

import pytest

from conftest import ROOT
from razbor03.checkers import (Verdict, agreement, check_frozen, check_judge, check_live, freeze, judge_prompt,
                               verdicts_from_dict, verdicts_to_dict)
from razbor03.runs import Answer, Run
from razbor03.scenarios import open_scenario
from razbor03.spec import load_suite

SUITE = load_suite(ROOT / "eval" / "questions.yaml")


@pytest.fixture(scope="module")
def frozen_base(data_dir):
    con, _ = open_scenario(data_dir, "base")
    try:
        return freeze(SUITE, con)
    finally:
        con.close()


def _run(values: dict[str, float]) -> Run:
    return Run("t", {}, [Answer(q, v, "₽", "пояснение") for q, v in values.items()])


def test_live_and_frozen_agree_on_same_data(data_dir, frozen_base):
    run = _run({"Q19": frozen_base["Q19"], "Q01": frozen_base["Q01"] * 1.1})
    con, _ = open_scenario(data_dir, "base")
    try:
        live = check_live(run, SUITE, con)
    finally:
        con.close()
    frozen = check_frozen(run, SUITE, frozen_base)
    assert {q: v.correct for q, v in live.items()} == {q: v.correct for q, v in frozen.items()} == {
        "Q19": True, "Q01": False}


def test_frozen_goes_stale_after_reload(data_dir, frozen_base):
    """После дозагрузки «последний месяц» — октябрь: замороженный эталон отвергает верный ответ и принимает старый."""
    con, _ = open_scenario(data_dir, "reload")
    try:
        october = con.execute(SUITE.get("Q19").check_sql).fetchone()[0]
        right, stale = _run({"Q19": float(october)}), _run({"Q19": frozen_base["Q19"]})
        assert check_live(right, SUITE, con)["Q19"].correct and not check_live(stale, SUITE, con)["Q19"].correct
    finally:
        con.close()
    assert not check_frozen(right, SUITE, frozen_base)["Q19"].correct
    assert check_frozen(stale, SUITE, frozen_base)["Q19"].correct


def test_none_answer_is_wrong_for_every_checker(data_dir, frozen_base):
    run = _run({"Q01": None})
    con, _ = open_scenario(data_dir, "base")
    try:
        assert not check_live(run, SUITE, con)["Q01"].correct
    finally:
        con.close()
    assert not check_frozen(run, SUITE, frozen_base)["Q01"].correct


class JudgeClient:
    """True/False — вердикт инструментом; строка — ответ текстом; Exception — сбой API."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        v = self.verdicts.pop(0)
        if isinstance(v, Exception):
            raise v
        if isinstance(v, str):
            block = NS(type="text", text=v)
        else:
            block = NS(type="tool_use", id="j", name="verdict", input={"correct": v, "reason": "так"})
        return NS(content=[block], stop_reason="end_turn", usage=NS(input_tokens=2000, output_tokens=100))


def test_judge_sees_question_answer_trace_but_no_reference():
    a = Answer("Q19", 392589.91, "₽", "октябрь неполный", [
        {"name": "run_sql", "input": {"sql": "SELECT 1"}, "output": "[{\"x\": 1}]", "is_error": False}])
    text = judge_prompt(SUITE.get("Q19").question, a)
    assert "последний месяц" in text and "392589.91" in text and "SELECT 1" in text and "октябрь неполный" in text
    assert "эталон" not in text.lower()
    assert "check_sql" not in text


def test_check_judge_forces_tool_counts_cost_and_survives_errors():
    client = JudgeClient([True, RuntimeError("503")])
    vs = check_judge(_run({"Q01": 1.0, "Q02": 2.0}), SUITE, client, "anthropic/claude-haiku-5.5")
    assert vs["Q01"].correct and vs["Q01"].cost_usd == pytest.approx(2000 * 0.10 / 1e6 + 100 * 0.50 / 1e6)
    assert not vs["Q02"].correct and vs["Q02"].note.startswith("error")
    assert client.calls[0]["tool_choice"] == {"type": "auto"} and client.calls[0]["tools"][0]["strict"] is True


def test_agreement_counts_missed_and_rejected():
    truth = {"Q1": Verdict(True), "Q2": Verdict(False), "Q3": Verdict(False), "Q4": Verdict(True)}
    other = {"Q1": Verdict(False), "Q2": Verdict(True), "Q3": Verdict(False), "Q4": Verdict(True)}
    assert agreement(truth, other) == {"answers": 4, "errors": 2, "missed": ["Q2"], "rejected": ["Q1"]}


def test_verdicts_roundtrip():
    vs = {"Q1": Verdict(True, 1.0, "n", 0.1)}
    assert verdicts_from_dict(verdicts_to_dict(vs)) == vs


def test_judge_writes_call_as_text_then_asked_again_with_structured_output():
    client = JudgeClient(['<invoke name="verdict"><parameter name="correct">true</parameter>', '{"correct": false, "reason": "не то"}'])
    v = check_judge(_run({"Q01": 1.0}), SUITE, client, "anthropic/claude-haiku-5.5")["Q01"]
    assert (v.correct, v.via, v.note) == (False, "json", "не то")
    assert client.calls[1]["output_config"]["format"]["type"] == "json_schema" and "tools" not in client.calls[1]
    assert v.cost_usd == pytest.approx(2 * (2000 * 0.10 / 1e6 + 100 * 0.50 / 1e6))


def test_tool_call_without_verdict_field_is_not_a_verdict():
    client = JudgeClient([None, "мусор"])
    client.verdicts[0] = None
    v = check_judge(_run({"Q01": 1.0}), SUITE, client, "anthropic/claude-haiku-5.5")["Q01"]
    assert v.via == "none" and not v.correct and v.note.startswith("судья не сдал")
