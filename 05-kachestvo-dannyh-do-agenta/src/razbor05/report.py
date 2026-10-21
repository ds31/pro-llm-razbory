"""HTML-отчёт пакета 05: дефекты по одному, «всё сразу» утро за утром, случайные сценарии, паспорта правил."""
from __future__ import annotations

from datetime import date
from html import escape

from .defects import DEFECTS
from .modes import SHORT
from .questions import QUESTIONS
from .rules import load_rules

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0 auto;max-width:1040px;padding:16px;color:#14181d;background:#fff}
h1{font-weight:500;font-size:26px;margin:8px 0}h2{font-weight:600;font-size:19px;margin-top:36px}
p{line-height:1.5}.meta{color:#5b6169;font-size:14px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #e4dfd2;padding:6px 8px;text-align:left;vertical-align:top}
th{color:#3a4048;font-weight:600;background:#f7f5ee}.ok{color:#0b7d4f}.bad{color:#d9363e}.mute{color:#5b6169}
.num{font-family:ui-monospace,Menlo,Consolas,monospace;text-align:right;white-space:nowrap}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:12px 0}
.card{border:1px solid #d8d2c2;border-radius:10px;padding:12px 14px;background:#f7f5ee}
.card b{display:block;font-size:24px;font-weight:500;margin:4px 0}.card span{font-size:13px;color:#3a4048}
.wrap{overflow-x:auto}.bar{display:inline-block;height:10px;background:#0b7d4f;border-radius:2px;vertical-align:middle}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
"""
KEYS = ("raw", "rules01", "gate")


def _d(s: str | None) -> str:
    return date.fromisoformat(s).strftime("%d.%m") if s else "не закрыт"


def _pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "нет данных"
    s = f"{v:+.1f}" if signed else f"{v:.1f}"
    return s.replace(".", ",").replace("-", "−") + " %"


def _err_cell(m: dict) -> str:
    v = m["error_pct"]
    cls = "ok" if v is not None and abs(v) <= 0.5 else "bad"
    return f'<td class="num {cls}">{_pct(v)}</td>'


def _rub(v) -> str:
    return "—" if v is None else f"{v:,.0f}".replace(",", " ") + " ₽"


def _label(defect: str) -> str:
    if defect == "clean":
        return "чистый поток"
    if defect == "all":
        return "всё сразу: восемь громких дефектов"
    return DEFECTS[defect][0]


def render_report(ref: dict) -> str:
    meta, show, rnd = ref["meta"], ref["showcase"], ref["random"]["summary"]
    parts = [f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Пакет 05 · качество данных до агента</title><style>{CSS}</style></head><body>",
             "<h1>Качество данных до агента: правила, карантин, закрытие месяца</h1>",
             f"<p class='meta'>Прогон {escape(meta['run_at'])} · поток октября 2026, seed {meta['feed_seed']} · "
             f"{rnd['scenarios']} случайных сценариев · без LLM: ответы — эталонные запросы слоя метрик пакета 01 · "
             f"допуск ±0,5 %</p>"]
    parts.append(_summary(show, rnd))
    parts.append(_showcase(show))
    parts.append(_timeline(show["all"]))
    parts.append(_random(rnd))
    parts.append(_rules(ref))
    parts.append("</body></html>")
    return "\n".join(parts)


def _summary(show: dict, rnd: dict) -> str:
    g, r, o = rnd["modes"]["gate"], rnd["modes"]["raw"], rnd["modes"]["rules01"]
    allm = show["all"]["modes"]
    silent = rnd["by_defect"].get("truncated", {"n": 0, "caught_any": 0})
    cards = [
        ("Октябрь закрыт", f"{_d(allm['raw']['close_day'])} → {_d(allm['gate']['close_day'])}",
         f"«всё сразу»: по календарю и воротами; ворота в {rnd['scenarios']} сценариях — медиана "
         f"{_d(g['close_day_median'])}, 90 % к {_d(g['close_day_p90'])}"),
        ("Выручка октября «всё сразу»", f"{_pct(allm['raw']['error_pct'])} / {_pct(allm['gate']['error_pct'])}",
         "без ворот / ворота, в день, когда месяц объявлен закрытым"),
        ("Неверный «закрытый» октябрь", f"{r['declared_wrong_loud_only']} / {o['declared_wrong_loud_only']} / "
                                        f"{g['declared_wrong_loud_only']} из {g['scenarios_loud_only']}",
         "без ворот / правила 01 / ворота — сценарии без обрезанных файлов"),
        ("Ложные блокировки", f"{sum(rnd['false_positives'].values())}",
         f"на {rnd['clean_files']:,} чистых файлах ({rnd['clean_rows']:,} строк)".replace(",", " ")),
        ("Тихий дефект", f"{g['declared_wrong_with_silent']} из {g['scenarios_with_silent']}",
         f"сценариев с обрезанными файлами ворота закрыли с ошибкой; R08 предупредило в {silent['caught_any']} "
         f"из {silent['n']}, но предупреждение строки не держит"),
    ]
    html = "".join(f"<div class='card'><span>{escape(t)}</span><b>{escape(v)}</b><span>{escape(n)}</span></div>"
                   for t, v, n in cards)
    return f"<section id='s-summary'><h2 id='summary'>Главное</h2><div class='cards'>{html}</div></section>"


def _showcase(show: dict) -> str:
    head = ("<tr><th rowspan='2'>Дефект</th><th rowspan='2'>Правило</th><th colspan='3'>Ошибка выручки октября "
            "в день закрытия</th><th colspan='3'>Октябрь закрыт</th><th colspan='3'>Верных из 9</th></tr><tr>"
            + "".join(f"<th>{SHORT[k]}</th>" for k in KEYS) * 3 + "</tr>")
    rows = []
    for name, sc in show.items():
        rule = "—" if name in ("clean", "all") else DEFECTS[name][1]
        caught = sc["detection"] and all(d["caught"] for d in sc["detection"])
        mark = "" if name == "clean" else (" <span class='ok'>поймано</span>" if caught
                                           else " <span class='bad'>не поймано</span>")
        m = sc["modes"]
        rows.append(f"<tr><td>{escape(_label(name))}</td><td>{rule}{mark}</td>"
                    + "".join(_err_cell(m[k]) for k in KEYS)
                    + "".join(f"<td class='num'>{_d(m[k]['close_day'])}</td>" for k in KEYS)
                    + "".join(f"<td class='num {'ok' if m[k]['correct_at_close'] == len(QUESTIONS) else 'bad'}'>"
                              f"{m[k]['correct_at_close']}</td>" for k in KEYS) + "</tr>")
    return ("<section id='s-defects'><h2 id='defects'>Один дефект — что искажает и что ловит</h2>"
            "<p>Каждый дефект внесён в октябрьский поток отдельно, в магазин №4 (регион «Восток»). Ошибка — выручка "
            "октября, которую конфигурация объявила окончательной, против правды. «Верных из 9» — вопросы про "
            "последний месяц (шесть из eval пакета 01 и три новых) в тот же день.</p>"
            f"<div class='wrap'><table>{head}{''.join(rows)}</table></div></section>")


def _timeline(sc: dict) -> str:
    rows_g, rows_a = [], []
    truth = sc["truth_revenue"]
    for row in sc["timeline"]:
        d = date.fromisoformat(row["day"])
        if not (date(2026, 10, 28) <= d <= date(2026, 11, 6)):
            continue
        g = row["gate"]
        viol = ", ".join(f"{k} × {v}" for k, v in g["violations"].items()) or "—"
        notes = "; ".join(g["requests"] and [f"запрос: {x}" for x in g["requests"]] or []) or ""
        miss = ", ".join(g["missing"]) or ""
        closes = "; ".join("закрытие " + c for c in g["closures"]) or ""
        rows_g.append(f"<tr><td class='num'>{d:%d.%m}</td><td class='num'>{g['loads']}</td>"
                      f"<td class='num'>{g['accepted']}</td><td>{escape(viol)}</td>"
                      f"<td class='num'>{g['released']}</td><td class='num'>{g['held_total']}</td>"
                      f"<td>{escape(' · '.join(x for x in [notes, ('нет файла: ' + miss) if miss else '', closes] if x))}"
                      f"</td></tr>")
        cells = []
        for k in KEYS:
            mm = row["modes"][k]
            ct = date.fromisoformat(mm["closed_through"])
            rev = mm["oct_revenue"]
            if rev is None:
                cells.append(f"<td class='mute'>по {ct:%d.%m}: отвечает сентябрём</td>")
            else:
                err = 100.0 * (rev - truth) / truth
                cls = "ok" if abs(err) <= 0.5 else "bad"
                cells.append(f"<td class='num {cls}'>{_rub(rev)} ({_pct(err)})</td>")
        rows_a.append(f"<tr><td class='num'>{d:%d.%m}</td>{''.join(cells)}</tr>")
    head_g = ("<tr><th>Утро</th><th>Файлов</th><th>Принято строк</th><th>Нарушения</th><th>Отпущено</th>"
              "<th>В карантине</th><th>Запросы, пропуски, закрытие</th></tr>")
    head_a = "<tr><th>Утро</th>" + "".join(f"<th>{SHORT[k]}</th>" for k in KEYS) + "</tr>"
    return ("<section id='s-timeline-gate'><h2 id='timeline'>Всё сразу: утро за утром</h2>"
            "<p>Восемь громких дефектов в одном октябре. Сверху — что делают ворота; снизу — какую выручку "
            f"октября видит агент в каждой конфигурации. Правда: {_rub(truth)}.</p>"
            f"<div class='wrap'><table>{head_g}{''.join(rows_g)}</table></div></section>"
            "<section id='s-timeline-agent'><h3>Что видит агент: выручка октября</h3>"
            f"<p class='meta'>Правда: {_rub(truth)}.</p>"
            f"<div class='wrap'><table>{head_a}{''.join(rows_a)}</table></div></section>")


def _random(rnd: dict) -> str:
    rows = []
    for k in DEFECTS:
        s = rnd["by_defect"].get(k)
        if not s:
            continue
        rows.append(f"<tr><td>{escape(DEFECTS[k][0])}</td><td>{DEFECTS[k][1]}</td><td class='num'>{s['n']}</td>"
                    f"<td class='num'>{s['caught']}</td><td class='num'>{s['caught_any']}</td></tr>")
    det = ("<tr><th>Дефект</th><th>Правило</th><th>Внесено</th><th>Поймано своим правилом</th>"
           f"<th>Поймано любым</th></tr>{''.join(rows)}")
    mrows = []
    labels = [("Объявили октябрь закрытым к 15.11", lambda m: f"{m['closed_by_sim_end']} из {m['scenarios']}"),
              ("Выручка октября дальше ±0,5 %, без обрезанных файлов",
               lambda m: f"{m['revenue_wrong_loud_only']} из {m['scenarios_loud_only']}"),
              ("Неверный октябрь, сценарии без обрезанных файлов",
               lambda m: f"{m['declared_wrong_loud_only']} из {m['scenarios_loud_only']}"),
              ("Неверный октябрь, сценарии с обрезанными файлами",
               lambda m: f"{m['declared_wrong_with_silent']} из {m['scenarios_with_silent']}"),
              ("Все 9 ответов верны в день закрытия", lambda m: f"{m['all9_correct_at_close']}"),
              ("Закрытый октябрь переписан задним числом", lambda m: f"{m['rewritten']}"),
              ("Медианная ошибка выручки октября",
               lambda m: f"{m['median_abs_error_pct']:.2f} %".replace(".", ",")),
              ("День закрытия: медиана · 90 % · последний",
               lambda m: f"{_d(m['close_day_median'])} · {_d(m['close_day_p90'])} · {_d(m['close_day_max'])}")]
    for name, f in labels:
        mrows.append(f"<tr><td>{name}</td>" + "".join(f"<td class='num'>{f(rnd['modes'][k])}</td>" for k in KEYS)
                     + "</tr>")
    modes = "<tr><th></th>" + "".join(f"<th>{SHORT[k]}</th>" for k in KEYS) + f"</tr>{''.join(mrows)}"
    hist = rnd["modes"]["gate"]["close_day_hist"]
    top = max(hist.values()) if hist else 1
    bars = "".join(f"<tr><td class='num'>{_d(d)}</td><td><span class='bar' style='width:{int(240 * n / top)}px'></span> "
                   f"{n}</td></tr>" for d, n in sorted(hist.items()))
    fp = rnd["false_positives"]
    fp_text = ("ни одного срабатывания" if not fp else
               ", ".join(f"{k}: {v}" for k, v in sorted(fp.items())))
    note = ("<p class='meta'>«Неверный октябрь» — выручка октября дальше ±0,5 % от правды или хотя бы один из девяти "
            "ответов неверен в день, когда конфигурация объявила месяц закрытым. Без ворот и в правилах 01 в этот день "
            "ещё нет части данных, поэтому ошибаются почти всегда.</p>")
    return ("<section id='s-random'><h2 id='random'>Случайные сценарии</h2>"
            f"<p>{rnd['scenarios']} сценариев с разными seed: в каждом от трёх до шести дефектов разных типов в "
            "случайных магазинах и днях октября, со случайной силой и задержкой исправления. На "
            f"{rnd['clean_files']:,} файлах, которых дефекты не касались, — {fp_text}.</p>".replace(",", " ")
            + f"<div class='wrap'><table>{det}</table></div>"
            f"</section><section id='s-random-modes'><h3>Что объявлено закрытым</h3>{note}<div class='wrap'><table>{modes}</table></div>"
            f"<h3>День закрытия октября воротами</h3><p class='meta'>По календарю — всегда 01.11.</p>"
            f"<table>{bars}</table></section>")


def _rules(ref: dict) -> str:
    rows = "".join(f"<tr><td><code>{r.id}</code></td><td>{escape(r.title)}</td><td>{r.severity}</td>"
                   f"<td>{r.action}</td><td>{r.fix}</td><td>{escape(r.why)}</td></tr>" for r in load_rules())
    hist = ref["history"]
    return ("<section id='s-rules'><h2 id='rules'>Правила</h2><p>Каждое правило — SQL-файл в <code>rules/</code>: возвращает строки-нарушения. "
            "block + drop — строка-мусор отбрасывается; block + hold — ждёт исправленного файла (resend), карточки "
            "(wait) или человека (reopen); warn — строка проходит, нарушение в журнале. История пакета 01 через те же "
            f"правила: R01 отбросило {hist['by_rule'].get('R01', 0)} строк, R07 предупредило о "
            f"{hist['by_rule'].get('R07', 0)} карточках-дублях — ровно ловушки пакета 01.</p>"
            "<div class='wrap'><table><tr><th>id</th><th>Правило</th><th>severity</th><th>action</th><th>fix</th>"
            f"<th>Почему</th></tr>{rows}</table></div></section>")
