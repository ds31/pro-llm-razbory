import json
import shutil

from razbor06.cli import main
from razbor06.discovery import load_discovery
from razbor06.paths import ROOT
from razbor06.scaffold import dump_acceptance, scaffold
from conftest import EXAMPLES


def test_check_filled_ready(capsys):
    assert main(["check", str(EXAMPLES / "discovery.yaml")]) == 0
    out = capsys.readouterr().out
    assert "готов к приёмке" in out and "raw.products: dup_cards" in out


def test_check_day1_lists_gaps(capsys):
    assert main(["check", str(EXAMPLES / "discovery-day1.yaml")]) == 1
    out = capsys.readouterr().out
    assert "не готов" in out and "M1" in out and "owner" in out


def test_scaffold_writes_file(tmp_path, capsys):
    out = tmp_path / "acceptance.yaml"
    assert main(["scaffold", str(EXAMPLES / "discovery.yaml"), "-o", str(out)]) == 0
    d = load_discovery(EXAMPLES / "discovery.yaml")
    assert out.read_text(encoding="utf-8") == dump_acceptance(scaffold(d), d)
    assert "7 кейсов" in capsys.readouterr().out


def test_all_writes_summary_and_exports(tmp_path, db, capsys):
    out = tmp_path / "out"
    local_db = tmp_path / "retail.duckdb"
    shutil.copyfile(db, local_db)
    assert main(["all", "--out", str(out), "--db", str(local_db)]) == 0
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["discovery"]["day1"]["ready"] is False and s["discovery"]["filled"]["ready"] is True
    assert s["acceptance"]["cases"] == 7 and s["acceptance"]["table_rows"] == 12
    assert s["variants"]["A"]["verdict"] == "не принят"
    assert s["variants"]["B"]["verdict"] == "ждёт прогона" and s["variants"]["B"]["waiting"] == 12
    assert (out / "report.md").exists() and (out / "acceptance.yaml").exists()
    assert (out / "agent-root-B" / "eval" / "questions.yaml").exists()
    text = capsys.readouterr().out
    assert "A: не принят" in text and "B: ждёт прогона" in text


def test_accept_exit_code_and_results(tmp_path, db):
    local_db = tmp_path / "retail.duckdb"
    shutil.copyfile(db, local_db)
    out = tmp_path / "out"
    assert main(["accept", "--variants", "B", "--out", str(out), "--db", str(local_db)]) == 1
    # прогон экспорта офлайн-эталоном (проверка труб, не агента) закрывает ворота
    from razbor01.cli import main as razbor01_main
    root = out / "agent-root-B"
    assert razbor01_main(["eval", "--root", str(root), "--offline", "--variants", "B"]) == 0
    assert main(["accept", "--variants", "B", "--out", str(out), "--db", str(local_db),
                 "--results", str(root / "eval" / "out" / "results.jsonl")]) == 0


def test_reference_run_matches_fresh_run(tmp_path, db):
    """Цифры статьи — eval/reference-run.json — воспроизводятся командой all (кроме даты прогона)."""
    local_db = tmp_path / "retail.duckdb"
    shutil.copyfile(db, local_db)
    out = tmp_path / "out"
    main(["all", "--out", str(out), "--db", str(local_db)])
    fresh = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    ref = json.loads((ROOT / "eval" / "reference-run.json").read_text(encoding="utf-8"))
    for s in (fresh, ref):
        s["meta"].pop("дата прогона")
    assert fresh == ref
