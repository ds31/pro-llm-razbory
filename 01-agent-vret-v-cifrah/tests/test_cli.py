import json
import shutil

import pytest

from conftest import ROOT
from razbor01.cli import main


def _copy_inputs(tmp_path):
    shutil.copy(ROOT / "metrics.yaml", tmp_path / "metrics.yaml")
    (tmp_path / "eval").mkdir()
    shutil.copy(ROOT / "eval" / "questions.yaml", tmp_path / "eval" / "questions.yaml")


def test_all_offline_one_command(tmp_path):
    _copy_inputs(tmp_path)
    assert main(["all", "--root", str(tmp_path), "--offline", "--limit", "3"]) == 0
    out = tmp_path / "eval" / "out"
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["summary"]["B"]["n"] == 3
    assert (out / "report.html").exists() and (out / "results.jsonl").read_text(encoding="utf-8").count("\n") == 6
    assert (tmp_path / "data" / "retail.duckdb").exists()


def test_only_and_variants(tmp_path):
    _copy_inputs(tmp_path)
    assert main(["eval", "--root", str(tmp_path), "--offline", "--only", "Q07,Q19", "--variants", "B"]) == 0
    summary = json.loads((tmp_path / "eval" / "out" / "summary.json").read_text(encoding="utf-8"))
    assert list(summary["summary"]) == ["B"] and summary["summary"]["B"]["n"] == 2


def test_offline_with_unpriced_model_does_not_crash(tmp_path):
    _copy_inputs(tmp_path)
    assert main(["eval", "--root", str(tmp_path), "--offline", "--model", "x", "--limit", "1"]) == 0


def test_unknown_model_stops_before_paid_run(tmp_path):
    assert main(["eval", "--root", str(tmp_path), "--model", "some-other-model"]) == 2
    assert not (tmp_path / "data").exists()


def test_cli_opens_db_only_via_open_db(tmp_path, monkeypatch):
    import razbor01.cli as cli
    from razbor01.tools import open_db
    _copy_inputs(tmp_path)
    opened = []

    def spy(path):
        opened.append(path)
        return open_db(path)
    monkeypatch.setattr(cli, "open_db", spy)
    assert main(["eval", "--root", str(tmp_path), "--offline", "--limit", "1"]) == 0
    assert len(opened) == 1


def test_console_line_shows_stop(tmp_path, capsys):
    _copy_inputs(tmp_path)
    main(["eval", "--root", str(tmp_path), "--offline", "--limit", "1", "--variants", "B"])
    assert "final_answer" in capsys.readouterr().out.split("\n")[1]


def test_results_written_as_they_arrive(tmp_path, monkeypatch):
    import razbor01.offline as offline
    _copy_inputs(tmp_path)
    orig = offline.OracleClient._create
    n = {"i": 0}

    def flaky(self, **kw):
        n["i"] += 1
        if n["i"] == 3:
            raise KeyboardInterrupt
        return orig(self, **kw)
    monkeypatch.setattr(offline.OracleClient, "_create", flaky)
    with pytest.raises(KeyboardInterrupt):
        main(["eval", "--root", str(tmp_path), "--offline", "--limit", "5", "--variants", "B"])
    lines = (tmp_path / "eval" / "out" / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_only_strips_spaces_and_rejects_unknown(tmp_path, capsys):
    _copy_inputs(tmp_path)
    assert main(["eval", "--root", str(tmp_path), "--offline", "--only", "Q07, Q19", "--variants", "B"]) == 0
    assert main(["eval", "--root", str(tmp_path), "--offline", "--only", "Q07,Q99"]) != 0
    assert "Q99" in capsys.readouterr().out
