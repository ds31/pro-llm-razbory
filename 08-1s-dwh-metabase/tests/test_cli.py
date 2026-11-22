"""Команда: демо-хранилище и метрика слоя пакета 01; отчёт прогона."""
import json

from razbor08 import cli
from razbor08.report import render


def test_demo_then_metric(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "PKG", tmp_path)
    cli.main(["demo", "--volume", "S", "--nights", "2"])
    assert (tmp_path / "data" / "dwh.duckdb").exists()
    capsys.readouterr()
    cli.main(["metric", "revenue", "--from", "2026-09-01", "--to", "2026-09-30", "--by", "region"])
    lines = capsys.readouterr().out.strip().splitlines()
    assert {ln.split("\t")[0] for ln in lines} == {"Север", "Юг", "Запад", "Восток"}


def test_report_renders(tmp_path):
    run = {"run_at": "2026-11-22T10:00:00", "nights": 1, "sim_start": "2026-10-19",
           "machine": {"cpu": "x", "cores": 1},
           "volumes": {"S": {"volume": {"stores": 1, "skus": 2, "history_days": 3},
                             "source": {"docs": 1, "lines": 2, "moves": 2},
                             "initial": {"requests": 1, "rows": 5, "bytes": 1000, "export_s": 0.1, "load_s": 0.1},
                             "strategies": {"full": {"label": "полная", "per_night": {
                                 "requests_avg": 1.0, "rows_avg": 5, "mb_avg": 0.01, "export_s_median": 0.1,
                                 "load_s_median": 0.1, "marts_s_median": 0.1}, "nights_with_errors": 0,
                                 "final": {"sales_days_bad": 0, "stock_cells_bad": 0, "month_end_cells_bad": 0}}}}}}
    p = render(run, tmp_path / "r.html")
    assert "полная" in p.read_text(encoding="utf-8")
    json.dumps(run)
