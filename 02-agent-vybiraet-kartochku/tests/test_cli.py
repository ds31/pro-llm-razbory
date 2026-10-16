import csv
import json
import shutil

from conftest import ROOT
from razbor02.cli import main, reference_view


def _copy_inputs(tmp_path, with_reference=True):
    for d in ["data", "audit", "eval/fixtures"]:
        shutil.copytree(ROOT / d, tmp_path / d)
    shutil.copy(ROOT / "eval" / "scenarios.yaml", tmp_path / "eval" / "scenarios.yaml")
    if with_reference:
        shutil.copy(ROOT / "eval" / "reference-run.json", tmp_path / "eval" / "reference-run.json")
    return tmp_path


def test_all_offline_one_command(tmp_path, capsys):
    root = _copy_inputs(tmp_path)
    assert main(["all", "--offline", "--root", str(root)]) == 0
    out = root / "eval" / "out"
    for f in ["live/summary.json", "live/tools.json", "live/search.json", "audit.json", "cards.csv", "run.json",
              "report.html"]:
        assert (out / f).exists(), f
    printed = capsys.readouterr().out
    assert "инструментов: 17" in printed and "совпадает с eval/reference-run.json" in printed


def test_reference_run_matches_fresh_offline_run(tmp_path):
    root = _copy_inputs(tmp_path)
    main(["all", "--offline", "--root", str(root)])
    fresh = json.loads((root / "eval" / "out" / "run.json").read_text(encoding="utf-8"))
    reference = json.loads((ROOT / "eval" / "reference-run.json").read_text(encoding="utf-8"))
    assert fresh == reference


def test_reference_view_shape():
    ref = json.loads((ROOT / "eval" / "reference-run.json").read_text(encoding="utf-8"))
    assert set(ref) >= {"package", "article", "audit", "shop_mcp_snapshot"}
    snap = ref["shop_mcp_snapshot"]
    assert snap["captured"] == "2026-10-17" and snap["tools"] == 17 and snap["ucp_version"] == "2026-08-25"
    a = ref["audit"]
    assert [s["id"] for s in a["scenarios"]] == ["S1", "S2", "S3", "S4", "S5"]
    assert len(a["top_blockers"]) == 5
    assert reference_view.__doc__


def test_mismatch_with_reference_fails_loudly(tmp_path, capsys):
    root = _copy_inputs(tmp_path)
    ref = json.loads((root / "eval" / "reference-run.json").read_text(encoding="utf-8"))
    ref["audit"]["cards"] = 999
    (root / "eval" / "reference-run.json").write_text(json.dumps(ref), encoding="utf-8")
    assert main(["all", "--offline", "--root", str(root)]) == 1
    assert "НЕ совпадает" in capsys.readouterr().out


def test_audit_own_catalog_without_erp(tmp_path, capsys):
    root = _copy_inputs(tmp_path, with_reference=False)
    own = tmp_path / "my.csv"
    shutil.copy(ROOT / "data" / "catalog.csv", own)
    assert main(["audit", "--root", str(root), "--catalog", str(own)]) == 0
    rows = list(csv.DictReader((root / "eval" / "out" / "cards.csv").open(encoding="utf-8")))
    assert len(rows) == 60 and {"sku", "score", "missing"} <= set(rows[0])
    assert "без учётной системы" in capsys.readouterr().out


def test_report_needs_probe_and_audit(tmp_path, capsys):
    root = _copy_inputs(tmp_path)
    assert main(["report", "--root", str(root)]) == 2
    assert "uv run razbor02 all" in capsys.readouterr().out
