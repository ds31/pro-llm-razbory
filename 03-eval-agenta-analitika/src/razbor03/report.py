"""HTML-отчёт эксперимента: три способа проверки, дозагрузка, повторы, ворота."""
from __future__ import annotations

from html import escape

from razbor01.runner import scrub

from .checkers import verdicts_from_dict
from .spec import Suite

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0 auto;max-width:1040px;padding:16px;color:#111;background:#fff}
h1{font-weight:400;font-size:26px}h2{font-weight:500;font-size:19px;margin-top:36px}
p.note{color:#545454;font-size:14px;max-width:760px}
table{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0}
th,td{border-bottom:1px solid #e7e7e7;padding:6px 8px;text-align:left;vertical-align:top}
th{color:#545454;font-weight:500}.ok{color:#009966}.bad{color:#d9363e}.mute{color:#8a8a8a}
.num{font-family:ui-monospace,Menlo,Consolas,monospace;text-align:right;white-space:nowrap}
.cell{text-align:center;font-family:ui-monospace,Menlo,Consolas,monospace}
.wrap{overflow-x:auto}.big{font-size:22px;font-weight:500}
pre{white-space:pre-wrap;word-break:break-word;font-size:13px;background:#f6f6f6;padding:10px;border-radius:6px}
.reason{font-size:13px;color:#333}
"""
JUDGE_LABEL = {"anthropic/claude-haiku-5.5": "Судья Claude Haiku 5.5", "anthropic/claude-sonnet-5.5": "Судья Claude Sonnet 5.5"}


def _e(x) -> str:
    return escape(scrub(str(x)))


def _num(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".replace(",", " ")


def _list(qs) -> str:
    return ", ".join(qs) if qs else "—"


def render(summary: dict, store: dict, suite: Suite, meta: dict) -> str:
    h = [f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' "
         f"content='width=device-width,initial-scale=1'><title>Eval агента-аналитика</title><style>{CSS}</style></head><body>",
         "<h1>Eval агента-аналитика: как доказать, что он считает правильно</h1>",
         f"<p class='note'>Агент: {_e(meta.get('model', ''))} · источник: {_e(meta.get('source', ''))} · "
         f"затраты на прогоны и судей: ${summary.get('cost_usd_total', 0):.2f}</p>"]

    ch = summary.get("checkers")
    if ch:
        h.append("<h2 id='checkers'>Три способа проверки на одних и тех же ответах</h2>")
        h.append(f"<p class='note'>{ch['live']['answers']} ответов прогона автора (A и B). Правда — живой эталон: "
                 f"check_sql по данным, допуск ±0,5 %. Настоящих ошибок: {ch['live']['errors']}.</p>")
        h.append("<div class='wrap'><table><tr><th>Проверяющий</th><th class='num'>Пропустил ошибок</th>"
                 "<th class='num'>Отверг верных</th><th>Какие</th><th class='num'>Цена, $</th></tr>")
        h.append(f"<tr><td>Живой эталон (check_sql)</td><td class='num ok'>0 из {ch['live']['errors']}</td>"
                 f"<td class='num ok'>0</td><td>—</td><td class='num'>0</td></tr>")
        for jm, a in ch.items():
            if jm == "live":
                continue
            h.append(f"<tr><td>{_e(JUDGE_LABEL.get(jm, jm))} без эталона</td>"
                     f"<td class='num {'bad' if a['missed'] else 'ok'}'>{len(a['missed'])} из {a['errors']}</td>"
                     f"<td class='num {'bad' if a['rejected'] else 'ok'}'>{len(a['rejected'])}</td>"
                     f"<td>пропустил: {_e(_list(a['missed']))}<br>отверг: {_e(_list(a['rejected']))}</td>"
                     f"<td class='num'>{a.get('cost_usd', 0):.3f}</td></tr>")
        h.append("</table></div>")
        h.append(_errors_table(summary, store, suite))

    dr = summary.get("drift")
    if dr:
        h.append("<h2 id='drift'>После дозагрузки: живой эталон против записанного числа</h2>")
        h.append("<p class='note'>Данные дозагружены по 10.11.2026: октябрь закрыт, «последний месяц» — октябрь. "
                 "reload-B — платформа обновлена; reload-stale-B — closed_through в слое метрик забыли сдвинуть.</p>")
        h.append("<div class='wrap'><table><tr><th>Прогон</th><th class='num'>Верно по живому эталону</th>"
                 "<th>Замороженное число (10.10)</th><th>SQL с датой внутри</th></tr>")
        for name, d in dr.items():
            f, s = d["frozen"], d["dated_sql"]
            h.append(f"<tr><td>{_e(name)}</td><td class='num'>{d['live_correct']} из {d['answers']}</td>"
                     f"<td>отверг верных: <b class='{'bad' if f['rejected'] else 'ok'}'>{len(f['rejected'])}</b> "
                     f"({_e(_list(f['rejected']))})<br>принял неверных: <b class='{'bad' if f['missed'] else 'ok'}'>"
                     f"{len(f['missed'])}</b> ({_e(_list(f['missed']))})</td>"
                     f"<td>отверг верных: <b>{len(s['rejected'])}</b> ({_e(_list(s['rejected']))})<br>"
                     f"принял неверных: <b>{len(s['missed'])}</b> ({_e(_list(s['missed']))})</td></tr>")
        h.append("</table></div>")

    st = summary.get("stability")
    if st:
        h.append("<h2 id='stability'>Устойчивость: один прогон — не доказательство</h2>")
        h.append("<div class='wrap'><table><tr><th>Вариант</th><th class='num'>Прогонов</th>"
                 "<th class='num'>Верно в каждом</th><th class='num'>pass@1</th><th class='num'>pass^k</th>"
                 "<th>Плавают</th><th>Всегда неверно</th></tr>")
        for v, s in st.items():
            h.append(f"<tr><td>{v}</td><td class='num'>{s['k']}</td><td class='num'>{' / '.join(map(str, s['per_run']))}"
                     f" из {s['questions']}</td><td class='num'>{100 * s['pass_at_1']:.1f} %</td>"
                     f"<td class='num'>{100 * s['pass_hat_k']:.1f} %</td><td>{_e(_list(s['flaky']))}</td>"
                     f"<td>{_e(_list(s['never']))}</td></tr>")
        h.append("</table></div>")
        h.append(_matrix(summary, store, suite))

    gt = summary.get("gate")
    if gt:
        h.append("<h2 id='gate'>Ворота: правка проходит, только если eval не упал</h2>")
        h.append("<div class='wrap'><table><tr><th>Правка</th><th>Было → стало</th><th class='num'>Вопросов</th>"
                 "<th>Регрессии</th><th class='num'>Код выхода</th></tr>")
        labels = {"no-anomaly-rule": "из layers.sql убрано правило аномалий",
                  "reload-stale": "дозагрузка без сдвига closed_through", "no-change": "без правок (повтор)"}
        for key, g in gt.items():
            nq = g["questions"] if isinstance(g["questions"], int) else len(g["questions"])
            new = g["new"] if isinstance(g["new"], str) else ", ".join(g["new"])
            h.append(f"<tr><td>{_e(labels.get(key, key))}</td><td>{_e(', '.join(g['old']))} → {_e(new)}</td>"
                     f"<td class='num'>{nq}</td><td class='{'bad' if g['regressions'] else 'ok'}'>"
                     f"{_e(_list(g['regressions']))}</td><td class='num big {'bad' if g['exit_code'] else 'ok'}'>"
                     f"{g['exit_code']}</td></tr>")
        h.append("</table></div>")
        h.append("<pre>uv run razbor03 compare --old ref:base-B-1 ref:base-B-2 ref:base-B-3 --new ref:no-anomaly-rule-B\n"
                 "# код выхода 1 — CI не пропускает правку</pre>")
    h.append("</body></html>")
    return "\n".join(h)


def _errors_table(summary: dict, store: dict, suite: Suite) -> str:
    """Ответы, которые живой эталон признал неверными, и что о них сказали судьи."""
    rows = []
    judges = store.get("judge", {})
    for rn in ("base-A-1", "base-B-1"):
        if rn not in store["runs"]:
            continue
        for a in store["runs"][rn]["answers"]:
            ref = summary.get("live", {}).get(rn, {}).get(a["qid"])
            if ref is None or ref["correct"]:
                continue
            cells = []
            for jm, per_run in judges.items():
                v = verdicts_from_dict(per_run.get(rn, {})).get(a["qid"])
                if v is None:
                    continue
                cls, word = ("bad", "«верно» — пропустил") if v.correct else ("ok", "«неверно» — поймал")
                cells.append(f"<div><b class='{cls}'>{_e(JUDGE_LABEL.get(jm, jm))}: {word}</b>"
                             f"<div class='reason'>{_e(v.note)}</div></div>")
            rows.append(f"<tr><td>{rn[5]} · {a['qid']}</td><td>{_e(suite.get(a['qid']).question)}</td>"
                        f"<td class='num bad'>{_num(a['value'])}</td><td class='num'>{_num(ref['expected'])}</td>"
                        f"<td>{''.join(cells)}</td></tr>")
    if not rows:
        return ""
    return ("<h2 id='errors'>Настоящие ошибки и вердикты судей</h2><div class='wrap'><table><tr><th>Ответ</th>"
            "<th>Вопрос</th><th class='num'>Агент</th><th class='num'>Эталон</th><th>Судьи</th></tr>"
            + "".join(rows) + "</table></div>")


def _matrix(summary: dict, store: dict, suite: Suite) -> str:
    live = summary.get("live", {})
    cols = [n for v in ("A", "B") for n in summary["stability"].get(v, {}).get("runs", [])]
    if not cols:
        return ""
    head = "".join(f"<th class='cell'>{_e(c.replace('base-', ''))}</th>" for c in cols)
    rows = []
    for q in suite.questions:
        marks = []
        for c in cols:
            v = live.get(c, {}).get(q.id)
            marks.append("<td class='cell mute'>·</td>" if v is None else
                         f"<td class='cell {'ok' if v['correct'] else 'bad'}'>{'✓' if v['correct'] else '✗'}</td>")
        rows.append(f"<tr><td>{q.id}</td><td class='mute'>{_e(suite.tags[q.tag])}</td>{''.join(marks)}</tr>")
    return (f"<div class='wrap'><table><tr><th>Вопрос</th><th>Ловушка</th>{head}</tr>" + "".join(rows)
            + "</table></div>")
