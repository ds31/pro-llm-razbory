import json
import os
import time

from razbor07.cli import main


def test_all_writes_run_and_report(tmp_path, capsys):
    assert main(["all", "-n", "2", "--workers", "1", "--root", str(tmp_path), "--reference"]) == 0
    ref = json.loads((tmp_path / "eval" / "out" / "run.json").read_text())
    assert set(ref) == {"meta", "main", "faults", "nights", "trace_example"}
    assert (tmp_path / "eval" / "reference-run.json").exists()
    html = (tmp_path / "eval" / "out" / "report.html").read_text()
    for anchor in ("id='night'", "id='result'", "id='faults'", "id='nights'", "id='trace'", "id='trace-prod'"):
        assert anchor in html
    assert "письмо не ушло повторно" in html
    out = capsys.readouterr().out
    assert "потеряно" in out and "Отчёт" in out


def test_night_and_trace_commands(capsys):
    assert main(["night", "--profile", "clean", "--config", "prod"]) == 0
    assert "доставлено" in capsys.readouterr().out
    assert main(["trace", "--config", "prod"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert lines[-1]["event"] == "done"


def test_health(tmp_path):
    f = tmp_path / "alive"
    assert main(["health", "--file", str(f)]) == 1
    f.touch()
    assert main(["health", "--file", str(f), "--max-age", "5"]) == 0
    old = time.time() - 60
    os.utime(f, (old, old))
    assert main(["health", "--file", str(f), "--max-age", "30"]) == 1
