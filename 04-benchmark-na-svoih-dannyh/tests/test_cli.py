import json

from razbor04.cli import main

from conftest import ROOT


def test_all_offline_one_command(tmp_path):
    assert main(["all", "--root", str(tmp_path), "--offline", "--limit", "2", "--models", "m1,m2"]) == 0
    out = tmp_path / "eval" / "out"
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert set(s["summary"]) == {"m1", "m2"} and s["summary"]["m1"]["B"]["n"] == 2
    assert (out / "report.html").exists()
    assert len(list((out / "runs").glob("*.jsonl"))) == 2


def test_unknown_model_stops_before_paid_run(tmp_path):
    assert main(["bench", "--root", str(tmp_path), "--models", "acme/unknown-1"]) == 2
    assert not (tmp_path / "data").exists()


def test_only_unknown_question(tmp_path):
    assert main(["bench", "--root", str(tmp_path), "--offline", "--models", "m", "--only", "Q99"]) == 2


def test_report_from_reference_run(tmp_path):
    """Отчёт статьи собирается из eval/reference-run.json без ключа и без базы."""
    assert main(["report", "--root", str(tmp_path), "--from", str(ROOT / "eval" / "reference-run.json")]) == 0
    html = (tmp_path / "eval" / "out" / "report.html").read_text(encoding="utf-8")
    assert "claude-opus-5.5" in html and "deepseek-v4.1-flash" in html


def test_models_command_lists_prices(capsys):
    assert main(["models"]) == 0
    assert "anthropic/claude-sonnet-5.5" in capsys.readouterr().out
