"""HTML-отчёт сравнения моделей: карта «точность × $ за ответ», сводка, ловушки, ответы по вопросам."""
from __future__ import annotations

import math
from html import escape

from razbor01.golden import TRAPS
from razbor01.report import TRAP_LABELS
from razbor01.runner import scrub

from .bench import BenchResult
from .prices import short

COLORS = ["#245f86", "#0b7d4f", "#e17100", "#d9363e", "#6b4fbb", "#3a4048"]
VARIANT_LABELS = {"A": "A — сырые таблицы", "B": "B — слой метрик"}
CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0 auto;max-width:1080px;padding:16px;color:#14181d;background:#fff}
h1{font-weight:500;font-size:26px}h2{font-weight:500;font-size:19px;margin-top:32px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #e4dfd2;padding:6px 8px;text-align:left;vertical-align:top}
th{color:#3a4048;font-weight:500}.num{font-family:ui-monospace,Menlo,Consolas,monospace;text-align:right;white-space:nowrap}
.ok{color:#0b7d4f}.bad{color:#d9363e}.muted{color:#5b6169}.wrap{overflow-x:auto}.legend{font-size:13px;color:#3a4048}
svg text{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
"""


def _money(v: float | None, digits: int = 4) -> str:
    return "—" if v is None else f"{v:.{digits}f}".replace(".", ",")


def _int(v: int) -> str:
    return f"{v:,}".replace(",", " ")


def _correct(s: dict) -> str:
    runs = s["correct_by_run"]
    base = f'{s["correct"]:g}'.replace(".", ",") + f' / {s["n"]}'
    return base + (f' <span class="muted">({"; ".join(map(str, runs))})</span>' if len(runs) > 1 else "")


def scatter_svg(summary: dict, w: int = 720, h: int = 420) -> str:
    """Карта: по X — $ за ответ (логарифмическая шкала), по Y — верных ответов. A — кружок, B — точка."""
    pts = [(m, v, s) for m, vs in summary.items() for v, s in vs.items()]
    if not pts:
        return ""
    costs = [max(s["usd_per_answer"], 1e-6) for _, _, s in pts]
    lo, hi = math.floor(math.log10(min(costs))), math.ceil(math.log10(max(costs)))
    hi = hi if hi > lo else lo + 1
    n = max(s["n"] for _, _, s in pts)
    ymin = max(0, 5 * math.floor((min(s["correct"] for _, _, s in pts) - 2) / 5))
    left, right, top, bottom = 64, 150, 24, 48
    X = lambda c: left + (math.log10(max(c, 1e-6)) - lo) / (hi - lo) * (w - left - right)
    Y = lambda k: top + (n - k) / max(n - ymin, 1) * (h - top - bottom)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%" role="img" '
             f'aria-label="Точность и цена ответа по моделям">']
    for d in range(lo, hi + 1):
        x = X(10 ** d)
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{h - bottom}" stroke="#e4dfd2"/>'
                     f'<text x="{x:.1f}" y="{h - bottom + 18}" font-size="12" text-anchor="middle" fill="#3a4048">'
                     f'${10 ** d:g}</text>')
    for k in range(ymin, n + 1, 5):
        y = Y(k)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="#e4dfd2"/>'
                     f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="12" text-anchor="end" fill="#3a4048">{k}</text>')
    parts.append(f'<text x="{(left + w - right) / 2:.0f}" y="{h - 8}" font-size="12" text-anchor="middle" '
                 f'fill="#3a4048">$ за ответ, логарифмическая шкала</text>'
                 f'<text x="14" y="{(top + h - bottom) / 2:.0f}" font-size="12" text-anchor="middle" fill="#3a4048" '
                 f'transform="rotate(-90 14 {(top + h - bottom) / 2:.0f})">верных ответов из {n}</text>')
    for i, (model, vs) in enumerate(summary.items()):
        col = COLORS[i % len(COLORS)]
        if "A" in vs and "B" in vs:
            parts.append(f'<line x1="{X(vs["A"]["usd_per_answer"]):.1f}" y1="{Y(vs["A"]["correct"]):.1f}" '
                         f'x2="{X(vs["B"]["usd_per_answer"]):.1f}" y2="{Y(vs["B"]["correct"]):.1f}" '
                         f'stroke="{col}" stroke-width="1.5" stroke-dasharray="4 3"/>')
        for v, s in vs.items():
            x, y = X(s["usd_per_answer"]), Y(s["correct"])
            fill = col if v == "B" else "#fff"
            parts.append(f'<circle class="pt {v}" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{fill}" stroke="{col}" '
                         f'stroke-width="2"><title>{escape(model)} · {v}: {s["correct"]:g}/{s["n"]}, '
                         f'${s["usd_per_answer"]:.4f}</title></circle>')
        last = vs.get("B") or next(iter(vs.values()))
        parts.append(f'<text x="{X(last["usd_per_answer"]) + 10:.1f}" y="{Y(last["correct"]) + 4:.1f}" font-size="12" '
                     f'fill="{col}">{escape(short(model))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_report(results: list[BenchResult], summary: dict, meta: dict) -> str:
    cols = [(m, v) for m, vs in summary.items() for v in vs]
    head = "".join(f"<th>{escape(short(m))}<br>{v}</th>" for m, v in cols)
    rows = []
    for m, vs in summary.items():
        for v, s in vs.items():
            rows.append(
                f"<tr><td>{escape(short(m))}</td><td>{VARIANT_LABELS.get(v, v)}</td>"
                f'<td class="num">{_correct(s)}</td><td class="num">{s["api_errors"]}</td>'
                f'<td class="num">{_money(s["usd_per_answer"])}</td>'
                f'<td class="num">{_money(s["list_usd_per_answer"])}</td>'
                f'<td class="num">{_money(s["usd_per_correct"])}</td>'
                f'<td class="num">{str(s["seconds_per_answer"]).replace(".", ",")}</td>'
                f'<td class="num">{str(s["steps_per_answer"]).replace(".", ",")}</td>'
                f'<td class="num">{_int(s["input_tokens_per_answer"])} / {_int(s["output_tokens_per_answer"])}</td></tr>')
    summary_table = ("<table><tr><th>Модель</th><th>Вариант</th><th>Верно</th><th>Ошибок API</th>"
                     "<th>$ за ответ</th><th>$ за ответ по прайсу</th><th>$ за верный ответ</th>"
                     "<th>с на ответ</th><th>шагов</th><th>токенов вход / выход</th></tr>" + "".join(rows) + "</table>")
    trap_rows = "".join(
        f"<tr><td>{TRAP_LABELS[t]}</td>" + "".join(
            f'<td class="num">{"; ".join(map(str, summary[m][v]["by_trap"][t]))} / {summary[m][v]["by_trap_n"][t]}</td>'
            if t in summary[m][v]["by_trap"] else "<td>—</td>" for m, v in cols) + "</tr>"
        for t in TRAPS)
    by_q: dict[str, dict] = {}
    for r in results:
        cell = by_q.setdefault(r.qid, {"q": r, "c": {}}).setdefault("c", {}).setdefault((r.model, r.variant), [])
        cell.append(r)
    q_rows = []
    for qid, d in by_q.items():
        q = d["q"]
        cells = []
        for key in cols:
            rs = d["c"].get(key, [])
            if not rs:
                cells.append("<td>—</td>")
                continue
            ok = sum(r.correct for r in rs)
            err = sum(r.api_error for r in rs)
            mark = "✓" if ok == len(rs) else ("API" if err == len(rs) else ("✗" if ok == 0 else f"{ok}/{len(rs)}"))
            cls = "ok" if ok == len(rs) else "bad"
            title = "; ".join(f"{r.got}" for r in rs)
            cells.append(f'<td class="num {cls}" title="{escape(title)}">{mark}</td>')
        q_rows.append(f"<tr><td>{qid}</td><td>{escape(q.question)}</td><td>{TRAP_LABELS.get(q.trap, q.trap)}</td>"
                      + "".join(cells) + "</tr>")
    meta_line = " · ".join(f"{escape(scrub(str(k)))}: {escape(scrub(str(v)))}" for k, v in meta.items())
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Бенчмарк моделей на своём eval</title><style>{CSS}</style></head><body>"
            f"<h1>Какую модель брать агенту: точность, цена, время на своём eval</h1><p class=\"muted\">{meta_line}</p>"
            f'<h2 id="map">Точность × $ за ответ</h2><div class="wrap">{scatter_svg(summary)}</div>'
            f'<p class="legend">Кружок — вариант A (сырые таблицы), точка — вариант B (слой метрик); '
            f"пунктир соединяет одну модель.</p>"
            f'<h2 id="summary">Сводка</h2><div class="wrap">{summary_table}</div>'
            f'<p class="legend">«$ за верный ответ» — все расходы варианта, делённые на число верных ответов. '
            f"«$ за ответ» — сколько списал шлюз (usage.cost OpenRouter), а если он цену не вернул — по прайсу; "
            f"«по прайсу» — токены × цена из prices.py. "
            f"Ошибки API не считаются неверными ответами.</p>"
            f'<h2 id="traps">По ловушкам</h2><div class="wrap"><table><tr><th>Ловушка</th>{head}</tr>{trap_rows}</table></div>'
            f'<h2 id="questions">Ответы по вопросам</h2><div class="wrap"><table><tr><th>№</th><th>Вопрос</th>'
            f'<th>Ловушка</th>{head}</tr>{"".join(q_rows)}</table></div></body></html>')
