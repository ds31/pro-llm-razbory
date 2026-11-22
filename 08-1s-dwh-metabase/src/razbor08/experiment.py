"""Эксперимент: четыре способа ночной загрузки на одной и той же жизни источника.

Источник живёт nights бизнес-дней (события — source.advance). После каждого дня — ночная
выгрузка в 02:00 каждым способом в своё хранилище, пересборка витрин и сверка с эталоном,
посчитанным прямо по источнику. Меряются запросы к источнику, прочитанные строки и байты,
время выгрузки, загрузки и витрин, расхождения витрин с эталоном.
"""
from __future__ import annotations

import os
import platform
import shutil
import statistics
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .dwh import Warehouse
from .source import DocFilter, Source1C, Volume, export_time
from .truth import compare, snapshot

STRATEGIES = {
    "full": "полная перезагрузка каждую ночь",
    "doc_date": "инкремент по дате документа: последние 3 дня",
    "watermark": "инкремент по дате изменения: всё, что изменилось после прошлого запуска",
    "safe": "дата изменения с перекрытием 2 часа + сверка контрольных сумм по воскресеньям",
}
DOC_DATE_WINDOW = 3
OVERLAP = timedelta(hours=2)
RECON_WEEKDAY = 6          # воскресенье


def _counters(src) -> tuple[int, int, int]:
    return src.requests, src.rows_read, src.bytes_out


def _drop_data(batch: Path) -> None:
    """Файлы пакета после загрузки удаляем, манифест оставляем — для разбора ночи."""
    for p in batch.glob("*.json"):
        if p.name != "manifest.json":
            p.unlink()


def reconcile(src, wh, at: datetime) -> list[tuple[str, date]]:
    """Сравнить контрольные суммы магазин × месяц; вернуть расходящиеся пары."""
    a = {(r["store_ref"], r["month"]): (r["docs"], r["qty"], r["amount"]) for r in src.control_totals(at)}
    b = {(r["store_ref"], r["month"]): (r["docs"], r["qty"], r["amount"]) for r in wh.control_totals()}
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def run_night(strategy: str, src, wh, day: date, batch_dir: Path) -> dict:
    t = export_time(day)
    c0 = _counters(src)
    last = wh.get_state("last_run")
    if strategy == "full":
        f = DocFilter.all()
    elif strategy == "doc_date":
        f = DocFilter.doc_date(day - timedelta(days=DOC_DATE_WINDOW - 1), day)
    elif strategy == "watermark":
        f = DocFilter.changed_since(datetime.fromisoformat(last))
    elif strategy == "safe":
        f = DocFilter.changed_since(datetime.fromisoformat(last) - OVERLAP)
    else:
        raise ValueError(strategy)
    t0 = time.perf_counter()
    src.export(batch_dir, t, f)
    export_s = time.perf_counter() - t0
    res = wh.load_batch(batch_dir)
    load_s = res.seconds
    _drop_data(batch_dir)
    if res.status == "applied":
        wh.set_state("last_run", t.isoformat())
    pairs: list = []
    if strategy == "safe" and day.weekday() == RECON_WEEKDAY:
        t0 = time.perf_counter()
        pairs = reconcile(src, wh, t)
        if pairs:
            rb = batch_dir.with_name(batch_dir.name + "-recon")
            src.export(rb, t, DocFilter.store_months(pairs))
            wh.load_batch(rb)
            _drop_data(rb)
        export_s += time.perf_counter() - t0
    marts_s = wh.build_marts(day)
    c1 = _counters(src)
    return {"day": day.isoformat(), "status": res.status, "requests": c1[0] - c0[0], "rows": c1[1] - c0[1],
            "bytes": c1[2] - c0[2], "export_s": round(export_s, 3), "load_s": round(load_s, 3),
            "marts_s": round(marts_s, 3), "held": len(res.held), "reconciled_pairs": len(pairs)}


def run_volume(volume: Volume, nights: int, sim_start: date, seed: int, work_dir, log=None) -> dict:
    work = Path(work_dir)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    say = log or (lambda *_: None)
    t0 = time.perf_counter()
    src = Source1C.create(work / "source.duckdb", volume, sim_start=sim_start, seed=seed)
    gen_s = time.perf_counter() - t0
    size = dict(zip(("docs", "lines", "moves"), (
        src.con.execute("SELECT count(*) FROM ib.docs").fetchone()[0],
        src.con.execute("SELECT count(*) FROM ib.doc_lines").fetchone()[0],
        src.con.execute("SELECT count(*) FROM ib.moves").fetchone()[0])))
    say(f"[{volume.name}] источник: {size['docs']} документов, {size['lines']} строк, {size['moves']} движений "
        f"({gen_s:.1f} с)")

    # первичная загрузка — одна на все способы, затем копия хранилища на каждый способ
    day0 = sim_start - timedelta(days=1)
    base = work / "wh-base.duckdb"
    wh = Warehouse(base)
    c0 = _counters(src)
    t0 = time.perf_counter()
    src.export(work / "landing" / "initial", export_time(day0), DocFilter.all())
    export_s = time.perf_counter() - t0
    res = wh.load_batch(work / "landing" / "initial")
    _drop_data(work / "landing" / "initial")
    wh.set_state("last_run", export_time(day0).isoformat())
    marts_s = wh.build_marts(day0)
    c1 = _counters(src)
    initial = {"requests": c1[0] - c0[0], "rows": c1[1] - c0[1], "bytes": c1[2] - c0[2],
               "export_s": round(export_s, 3), "load_s": round(res.seconds, 3), "marts_s": round(marts_s, 3),
               "status": res.status}
    wh.close()
    whs = {}
    for k in STRATEGIES:
        p = work / f"wh-{k}.duckdb"
        shutil.copy(base, p)
        whs[k] = Warehouse(p)
    say(f"[{volume.name}] первичная загрузка: {initial['rows']} строк, {initial['bytes'] / 1e6:.0f} МБ, "
        f"{initial['requests']} запросов, выгрузка {export_s:.1f} с, загрузка {res.seconds:.1f} с")

    series: dict[str, list] = {k: [] for k in STRATEGIES}
    events = []
    for i in range(nights):
        day = sim_start + timedelta(days=i)
        events.append(src.advance(day))
        t = export_time(day)
        snap = snapshot(src, t, day, work / "truth")
        for k in STRATEGIES:
            night = run_night(k, src, whs[k], day, work / "landing" / k / day.isoformat())
            night.update(compare(whs[k], snap))
            series[k].append(night)
        say(f"[{volume.name}] {day.isoformat()}: " + ", ".join(
            f"{k} {series[k][-1]['rows']} строк/{series[k][-1]['sales_days_bad']} расх." for k in STRATEGIES))
    for w in whs.values():
        w.close()
    src.close()

    out = {"volume": volume.__dict__, "source": size, "initial": initial, "events": events, "strategies": {}}
    for k, s in series.items():
        out["strategies"][k] = {
            "label": STRATEGIES[k],
            "per_night": {
                "requests_avg": round(statistics.mean(n["requests"] for n in s), 1),
                "rows_avg": round(statistics.mean(n["rows"] for n in s)),
                "mb_avg": round(statistics.mean(n["bytes"] for n in s) / 1e6, 2),
                "export_s_median": round(statistics.median(n["export_s"] for n in s), 3),
                "load_s_median": round(statistics.median(n["load_s"] for n in s), 3),
                "marts_s_median": round(statistics.median(n["marts_s"] for n in s), 3),
            },
            "nights_with_errors": sum(1 for n in s if n["sales_days_bad"] or n["stock_cells_bad"]
                                      or n["month_end_cells_bad"]),
            "max_sales_days_bad": max(n["sales_days_bad"] for n in s),
            "max_store_months_bad": max(n["store_months_bad"] for n in s),
            "final": {k2: s[-1][k2] for k2 in ("sales_days_bad", "stock_cells_bad", "month_end_cells_bad",
                                                "store_months_bad", "last_full_month_err_pct",
                                                "revenue_abs_err", "revenue_total", "sales_days")},
            "series": s,
        }
    return out


def machine() -> dict:
    cpu = platform.processor() or platform.machine()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {"cpu": cpu, "cores": os.cpu_count(), "python": platform.python_version()}
