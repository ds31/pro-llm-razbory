"""HTML-отчёт eval: сводка A и B, разбивка по ловушкам, ответы и трассы по каждому вопросу."""
from __future__ import annotations

from html import escape

from .golden import TRAPS, is_correct
from .runner import QuestionResult, scrub

PASS_MIN_B = 27  # критерий «прошёл»: вариант B верно отвечает минимум на 27 вопросов из 30
TRAP_LABELS = {
    "none": "без ловушки", "dup_join": "дубли в справочнике", "anomaly": "аномальные строки",
    "open_month": "незакрытый месяц", "definition": "определение метрики",
}
CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0 auto;max-width:1040px;padding:16px;color:#111}
h1{font-weight:400;font-size:26px}h2{font-weight:500;font-size:18px;margin-top:32px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #e7e7e7;padding:6px 8px;text-align:left;vertical-align:top}
th{color:#545454;font-weight:500}.ok{color:#009966}.bad{color:#d9363e}.num{font-family:ui-monospace,Menlo,Consolas,monospace;text-align:right}
.verdict{display:inline-block;border:1px solid #dbdbdb;border-radius:8px;padding:6px 12px;margin:8px 0}
details{border:1px solid #e7e7e7;border-radius:8px;margin:8px 0;padding:8px 12px}summary{cursor:pointer}
pre{white-space:pre-wrap;word-break:break-word;font-size:12px;background:#fafafa;padding:8px;border-radius:6px}
.wrap{overflow-x:auto}
"""


def _num(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".replace(",", " ")


def _e(text) -> str:
    """Текст агента и модели: без путей и пользователя ОС, с экранированием HTML."""
    return escape(scrub(str(text)))


def _trap_note(r: QuestionResult) -> str:
    if r.correct or r.trap_value is None or not is_correct(r.got, r.trap_value):
        return ""
    return f' · <b class="bad">попал в ловушку «{TRAP_LABELS[r.trap]}»</b>'


def render_report(results: list[QuestionResult], summary: dict, meta: dict) -> str:
    b = summary.get("B", {})
    passed = b.get("correct", 0) >= PASS_MIN_B
    verdict = (f'<p class="verdict {"ok" if passed else "bad"}">Критерий «прошёл» (B ≥ {PASS_MIN_B}/30): '
               f'{"да" if passed else "нет"}</p>')
    head = "".join(f"<th>{v}</th>" for v in summary)
    rows = [
        ("Верных ответов", lambda s: f'{s["correct"]}/{s["n"]} ({s["accuracy_pct"]} %)'),
        ("Цена за вопрос, $", lambda s: f'{s["cost_usd_per_q"]:.4f}'),
        ("Время на вопрос, с", lambda s: f'{s["seconds_per_q"]}'),
    ]
    sum_rows = "".join(f"<tr><td>{name}</td>" + "".join(f'<td class="num">{f(s)}</td>' for s in summary.values())
                       + "</tr>" for name, f in rows)
    trap_rows = "".join(
        f"<tr><td>{TRAP_LABELS[t]}</td>" + "".join(f'<td class="num">{s["by_trap"].get(t, "—")}</td>'
                                                   for s in summary.values()) + "</tr>"
        for t in TRAPS)
    by_q: dict[str, dict[str, QuestionResult]] = {}
    for r in results:
        by_q.setdefault(r.qid, {})[r.variant] = r
    q_rows, traces = [], []
    for qid, vs in by_q.items():
        first = next(iter(vs.values()))
        cells = "".join(
            f'<td class="num {"ok" if vs[v].correct else "bad"}">{_num(vs[v].got)}{"<br><small>ловушка</small>" if _trap_note(vs[v]) else ""}</td>' if v in vs else "<td>—</td>"
            for v in summary)
        q_rows.append(f"<tr><td>{qid}</td><td>{escape(first.question)}</td><td>{TRAP_LABELS[first.trap]}</td>"
                      f'<td class="num">{_num(first.expected)}</td>{cells}</tr>')
        for v, r in vs.items():
            steps = "".join(
                f"<li><b>{_e(c.name)}</b>{' — ошибка' if c.is_error else ''}"
                f"<pre>{_e(c.input)}</pre>" + (f"<pre>{_e(c.output[:2000])}</pre>" if c.output else "")
                + "</li>" for c in r.run.trace)
            traces.append(
                f'<details id="trace-{qid}-{v}"><summary>{qid} · вариант {v} · '
                f'<span class="{"ok" if r.correct else "bad"}">{"верно" if r.correct else "неверно"}</span> · '
                f'{_num(r.got)} при эталоне {_num(r.expected)}{_trap_note(r)}</summary>'
                f"<p>{escape(r.question)}</p><ol>{steps}</ol>"
                f"<p>Остановка: {_e(r.stop)}. Метрика: {_e(r.run.metric_id)}. "
                f"Пояснение агента: {_e(r.run.explanation)}</p></details>")
    meta_line = " · ".join(f"{_e(k)}: {_e(v)}" for k, v in meta.items())
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Eval агента-аналитика: A и B</title><style>{CSS}</style></head><body>"
            f"<h1>Агент на сырых таблицах (A) и на слое метрик (B)</h1><p>{meta_line}</p>{verdict}"
            f'<h2 id="summary">Сводка</h2><div class="wrap"><table><tr><th></th>{head}</tr>{sum_rows}</table></div>'
            f'<h2 id="traps">По ловушкам</h2><div class="wrap"><table><tr><th>Ловушка</th>{head}</tr>{trap_rows}</table></div>'
            f'<h2 id="questions">Вопросы</h2><div class="wrap"><table><tr><th>№</th><th>Вопрос</th><th>Ловушка</th>'
            f'<th>Эталон</th>{head}</tr>{"".join(q_rows)}</table></div>'
            f'<h2 id="traces">Трассы</h2>{"".join(traces)}</body></html>')
