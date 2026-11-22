"""Команда razbor08: прогон эксперимента, демо-хранилище, слой метрик пакета 01, публикация в Postgres."""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .experiment import STRATEGIES, machine, run_night, run_volume
from .source import VOLUMES, DocFilter, Source1C, export_time

PKG = Path(__file__).resolve().parents[2]
SIM_START = date(2026, 10, 19)       # понедельник; 28 ночей — четыре воскресные сверки
NIGHTS = 28
SEED = 8


def _say(msg: str) -> None:
    print(msg, flush=True)


def cmd_all(a) -> None:
    vols = [v.strip() for v in a.volumes.split(",")]
    nights = 7 if a.quick else a.nights
    if a.quick:
        vols = ["S"]
    run = {"run_at": datetime.now().isoformat(timespec="seconds"), "sim_start": SIM_START.isoformat(),
           "nights": nights, "seed": SEED, "machine": machine(),
           "params": {"strategies": STRATEGIES, "page_objects": 500, "page_rows": 5000, "export_at": "02:00",
                      "doc_date_window_days": 3, "overlap_hours": 2, "reconcile": "воскресенье"},
           "volumes": {}}
    t0 = time.perf_counter()
    for v in vols:
        run["volumes"][v] = run_volume(VOLUMES[v], nights, SIM_START, SEED, PKG / "data" / "work" / v, log=_say)
    run["seconds"] = round(time.perf_counter() - t0, 1)
    out = PKG / "eval" / ("reference-run.json" if a.reference else "out/run.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(run, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    from .report import render
    rep = render(run, PKG / "eval" / "out" / "report.html")
    _say(f"Готово за {run['seconds']} с: {out.relative_to(PKG)}, отчёт {rep.relative_to(PKG)}")
    for v, r in run["volumes"].items():
        for k, s in r["strategies"].items():
            p, f = s["per_night"], s["final"]
            _say(f"  {v} {k:9s} строк/ночь {p['rows_avg']:>9}  МБ/ночь {p['mb_avg']:>8}  "
                 f"выгрузка {p['export_s_median']:>6} с  ошибок в последнюю ночь: {f['sales_days_bad']} дн., "
                 f"{f['stock_cells_bad'] + f['month_end_cells_bad']} ост., {f['store_months_bad']} маг.-мес.")


def cmd_demo(a) -> None:
    """Демо-хранилище data/dwh.duckdb: способ safe, nights ночей — для Metabase и слоя метрик."""
    from .dwh import Warehouse
    from .truth import compare, snapshot
    vol = VOLUMES[a.volume]
    work = PKG / "data" / "demo"
    work.mkdir(parents=True, exist_ok=True)
    src = Source1C.create(work / "source.duckdb", vol, sim_start=SIM_START, seed=SEED)
    dwh_path = PKG / "data" / "dwh.duckdb"
    for f in (dwh_path, dwh_path.with_suffix(".duckdb.wal")):
        if f.exists():
            f.unlink()
    wh = Warehouse(dwh_path)
    day0 = SIM_START - timedelta(days=1)
    src.export(work / "landing" / "initial", export_time(day0), DocFilter.all())
    wh.load_batch(work / "landing" / "initial")
    wh.set_state("last_run", export_time(day0).isoformat())
    for i in range(a.nights):
        day = SIM_START + timedelta(days=i)
        src.advance(day)
        n = run_night("safe", src, wh, day, work / "landing" / day.isoformat())
        d = compare(wh, snapshot(src, export_time(day), day, work / "truth"))
        _say(f"{day}: {n['requests']} запросов, {n['rows']} строк, сверка пар: {n['reconciled_pairs']}, "
             f"расхождений: {d['sales_days_bad']} магазино-дней")
    wh.close()
    src.close()
    _say(f"Хранилище: {dwh_path.relative_to(PKG)} (схемы raw, stg, mart, meta)")


def cmd_metric(a) -> None:
    from .agent_bridge import metric
    from .dwh import Warehouse
    wh = Warehouse(PKG / "data" / "dwh.duckdb")
    by = tuple(x for x in (a.by or "").split(",") if x)
    rows = metric(wh, a.metric, date.fromisoformat(a.date_from), date.fromisoformat(a.date_to), by,
                  closed_through=date.fromisoformat(a.closed_through) if a.closed_through else None)
    for r in rows:
        print(*r, sep="\t")
    wh.close()


def cmd_publish(a) -> None:
    from .dwh import Warehouse
    from .publish import publish
    wh = Warehouse(PKG / "data" / "dwh.duckdb")
    for t, n in publish(wh, a.dsn).items():
        _say(f"mart.{t}: {n} строк")
    wh.close()


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="razbor08", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("all", help="эксперимент: 4 способа × объёмы × ночи, отчёт")
    s.add_argument("--volumes", default="S,M,L")
    s.add_argument("--nights", type=int, default=NIGHTS)
    s.add_argument("--quick", action="store_true", help="только объём S и 7 ночей")
    s.add_argument("--reference", action="store_true", help="записать eval/reference-run.json")
    s.set_defaults(fn=cmd_all)
    s = sub.add_parser("demo", help="демо-хранилище data/dwh.duckdb способом safe")
    s.add_argument("--volume", default="S", choices=list(VOLUMES))
    s.add_argument("--nights", type=int, default=NIGHTS)
    s.set_defaults(fn=cmd_demo)
    s = sub.add_parser("metric", help="метрика слоя пакета 01 по data/dwh.duckdb")
    s.add_argument("metric")
    s.add_argument("--from", dest="date_from", required=True)
    s.add_argument("--to", dest="date_to", required=True)
    s.add_argument("--by", default="")
    s.add_argument("--closed-through", default=None)
    s.set_defaults(fn=cmd_metric)
    s = sub.add_parser("publish", help="витрины data/dwh.duckdb → Postgres (нужен --extra pg)")
    s.add_argument("--dsn", default="postgresql://razbor08:razbor08@localhost:5452/dwh")
    s.set_defaults(fn=cmd_publish)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
