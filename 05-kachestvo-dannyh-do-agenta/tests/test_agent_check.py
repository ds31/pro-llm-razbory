"""Офлайн-проверка агента: эталонные запросы слоя метрик на витрине ворот; прогон автора совпадает с ними."""
import json

import pytest

from razbor01.golden import is_correct
from razbor05.agent_check import QIDS, run, summarize
from tests.conftest import ROOT


@pytest.fixture(scope="module")
def offline(base, tmp_path_factory):
    return run(base, tmp_path_factory.mktemp("snap") / "gate.duckdb", client=None)


def test_offline_calendar_vs_gates(offline):
    answers, state = offline
    assert state["gate_closed_through"] == "2026-09-30"          # 03.11 октябрь ещё не прошёл чек-лист
    s = summarize(answers)
    assert s["gates"]["correct"] == len(QIDS)
    assert s["calendar"]["correct"] < len(QIDS)


def test_author_agent_run_matches_offline(offline):
    answers, _ = offline
    author = json.loads((ROOT / "eval" / "agent-run.json").read_text(encoding="utf-8"))
    off = {(a.setup, a.qid): a.got for a in answers}
    for a in author["answers"]:
        assert is_correct(a["got"], off[(a["setup"], a["qid"])]), (a["setup"], a["qid"])
    assert author["summary"]["gates"]["correct"] == len(QIDS)
    assert sum(v["cost_usd"] for v in author["summary"].values()) < 1.0
