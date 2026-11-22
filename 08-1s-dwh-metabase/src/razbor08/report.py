"""HTML-отчёт прогона: по объёму — нагрузка на источник, время и расхождения каждого способа."""
from __future__ import annotations

import html
from pathlib import Path


def _fmt(n) -> str:
    if isinstance(n, float):
        return f"{n:,.2f}".replace(",", " ").replace(".", ",")
    return f"{n:,}".replace(",", " ")


def render(run: dict, path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = ["<!doctype html><meta charset='utf-8'><title>Разбор 08 — прогон</title>",
             "<style>body{font:15px/1.45 system-ui,sans-serif;margin:24px;max-width:1100px;color:#1d1d1b}"
             "table{border-collapse:collapse;margin:12px 0 28px}td,th{border:1px solid #ccc;padding:4px 8px;"
             "text-align:right}th:first-child,td:first-child{text-align:left}.bad{color:#b3261e;font-weight:600}"
             ".ok{color:#1b6e3a}</style>",
             f"<h1>Разбор 08 — ночная загрузка из «1С»</h1><p>Прогон {html.escape(run['run_at'])}, "
             f"{run['nights']} ночей с {run['sim_start']}, машина: {html.escape(run['machine']['cpu'])}, "
             f"{run['machine']['cores']} ядер.</p>"]
    for name, v in run["volumes"].items():
        vol = v["volume"]
        ini = v["initial"]
        parts.append(f"<h2>Объём {name}: {vol['stores']} магазинов, {vol['skus']} товаров, "
                     f"{vol['history_days']} дней истории</h2>")
        parts.append(f"<p>В источнике {_fmt(v['source']['docs'])} документов, {_fmt(v['source']['lines'])} строк "
                     f"табличных частей, {_fmt(v['source']['moves'])} движений регистра. Первичная загрузка: "
                     f"{_fmt(ini['requests'])} запросов, {_fmt(ini['rows'])} строк, {_fmt(round(ini['bytes'] / 1e6))} МБ, "
                     f"выгрузка {_fmt(ini['export_s'])} с, загрузка {_fmt(ini['load_s'])} с.</p>")
        parts.append("<table><tr><th>Способ</th><th>Запросов за ночь</th><th>Строк за ночь</th><th>МБ за ночь</th>"
                     "<th>Выгрузка, с</th><th>Загрузка, с</th><th>Витрины, с</th><th>Ночей с расхождением</th>"
                     "<th>Магазино-дней с ошибкой в последнюю ночь</th><th>Ячеек остатков с ошибкой</th></tr>")
        for k, s in v["strategies"].items():
            p, f = s["per_night"], s["final"]
            cls = "bad" if f["sales_days_bad"] or f["stock_cells_bad"] else "ok"
            parts.append(f"<tr><td>{html.escape(s['label'])}</td><td>{_fmt(p['requests_avg'])}</td>"
                         f"<td>{_fmt(p['rows_avg'])}</td><td>{_fmt(p['mb_avg'])}</td>"
                         f"<td>{_fmt(p['export_s_median'])}</td><td>{_fmt(p['load_s_median'])}</td>"
                         f"<td>{_fmt(p['marts_s_median'])}</td><td>{s['nights_with_errors']} из {run['nights']}</td>"
                         f"<td class='{cls}'>{_fmt(f['sales_days_bad'])}</td>"
                         f"<td class='{cls}'>{_fmt(f['stock_cells_bad'] + f['month_end_cells_bad'])}</td></tr>")
        parts.append("</table>")
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
