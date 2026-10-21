"""Запуск одной командой на временной копии и сверка с прогоном автора."""
import json

import pytest

from razbor05.cli import main
from tests.conftest import ROOT


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("pkg")
    assert main(["all", "--root", str(root), "-n", "2", "--workers", "1"]) == 0
    return root, json.loads((root / "eval" / "out" / "run.json").read_text(encoding="utf-8"))


def test_report_written(run):
    root, ref = run
    html = (root / "eval" / "out" / "report.html").read_text(encoding="utf-8")
    for anchor in ("id='summary'", "id='defects'", "id='timeline'", "id='random'", "id='rules'"):
        assert anchor in html
    assert "/home/" not in html and "/tmp/" not in html


def test_matches_author_reference(run):
    """Цифры статьи воспроизводятся: витрина и первые сценарии совпадают с eval/reference-run.json."""
    _, ref = run
    author = json.loads((ROOT / "eval" / "reference-run.json").read_text(encoding="utf-8"))
    for name, sc in ref["showcase"].items():
        for k in ("raw", "rules01", "gate"):
            a, b = sc["modes"][k], author["showcase"][name]["modes"][k]
            assert (a["close_day"], a["correct_at_close"], a["rewritten"]) == \
                (b["close_day"], b["correct_at_close"], b["rewritten"]), (name, k)
            assert a["error_pct"] == pytest.approx(b["error_pct"], abs=1e-9), (name, k)
    assert ref["random"]["scenarios"] == author["random"]["scenarios"][:2]
    assert ref["history"] == author["history"]


def test_rules_command(capsys):
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "R01" in out and "R09" in out


def test_author_run_passes_criteria():
    """Критерий «прошёл» из eval/README.md на прогоне автора."""
    ref = json.loads((ROOT / "eval" / "reference-run.json").read_text(encoding="utf-8"))
    s = ref["random"]["summary"]
    loud = {k: v for k, v in s["by_defect"].items() if k != "truncated"}
    assert all(v["caught"] == v["n"] for v in loud.values()), loud
    assert s["false_positives"] == {}
    g = s["modes"]["gate"]
    assert g["rewritten"] == 0 and g["declared_wrong_loud_only"] == 0
    assert s["scenarios"] == 200
