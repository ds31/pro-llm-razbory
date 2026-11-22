"""HTML-отчёт пакета 07: ночь, итог по конфигурациям, сбои по одному, N ночей, трасса одной задачи."""
from __future__ import annotations

from html import escape

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0 auto;max-width:1040px;padding:16px;color:#14181d;background:#fff}
h1{font-weight:500;font-size:26px;margin:8px 0}h2{font-weight:600;font-size:19px;margin-top:36px}
p{line-height:1.5}.meta{color:#5b6169;font-size:14px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #e4dfd2;padding:6px 8px;text-align:left;vertical-align:top}
th{color:#3a4048;font-weight:600;background:#f7f5ee}.ok{color:#0b7d4f}.bad{color:#d9363e}.mute{color:#5b6169}
.num{font-family:ui-monospace,Menlo,Consolas,monospace;text-align:right;white-space:nowrap}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:12px 0}
.card{border:1px solid #d8d2c2;border-radius:10px;padding:12px 14px;background:#f7f5ee}
.card b{display:block;font-size:22px;font-weight:500;margin:4px 0}.card span{font-size:13px;color:#3a4048}
.wrap{overflow-x:auto}code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
.ev{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px}
section{scroll-margin-top:8px}
"""
NAMES = {"naive": "Наивная", "queue": "Очередь без идемпотентности", "prod": "Прод"}
EVENTS = {
    "received": "API принял, 202", "claimed": "воркер взял задачу", "call": "вызов модели",
    "send": "письмо магазину ушло", "send_deduped": "письмо не ушло повторно: ключ уже был",
    "done": "готово", "retry_scheduled": "повтор по backoff", "dead": "в dead-letter",
    "lease_expired": "аренда истекла: воркер убит", "request_start": "запрос в API",
    "request_error": "ошибка 500 клиенту", "request_done": "ответ 200 клиенту",
    "client_timeout": "клиент не дождался и переспросит", "refused": "API лежит: соединение отклонено",
    "lost_lease": "аренда уже чужая",
}


def _n(v, digits=0) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{digits}f}".replace(",", " ").replace(".", ",")
    return s.replace("-", "−")


def _sec(v) -> str:
    if v is None:
        return "—"
    if v >= 120:
        return _n(v / 60, 1) + " мин"
    return _n(v, 1) + " с"


def _cls(ok: bool) -> str:
    return "ok" if ok else "bad"


def _main_table(main: dict) -> str:
    rows = [
        ("Доставлено ответов", lambda m: _n(m["delivered"]), None),
        ("Потеряно: ответа нет и в dead-letter нет", lambda m: _n(m["lost"]), lambda m: m["lost"] == 0),
        ("Дубли: магазин получил ответ дважды", lambda m: _n(m["dup_tasks"]), lambda m: m["dup_tasks"] == 0),
        ("В dead-letter, с причиной", lambda m: _n(m["dead"]), None),
        ("p50 до ответа", lambda m: _sec(m["p50"]), None),
        ("p95 до ответа", lambda m: _sec(m["p95"]), None),
        ("Трасса до конечного статуса", lambda m: f'{_n(m["trace_complete"])} из {_n(m["tasks"])}',
         lambda m: m["trace_complete"] == m["tasks"]),
        ("Вызовов модели на доставленный ответ", lambda m: _n(m["calls_per_delivered"], 2), None),
        ("Отказов 429 от провайдера", lambda m: _n(m["rejected_429"]), None),
        ("kill -9 за ночь", lambda m: _n(m["crashes"]), None),
    ]
    head = "<tr><th></th>" + "".join(f"<th class='num'>{NAMES[k]}</th>" for k in main) + "</tr>"
    body = ""
    for label, fmt, good in rows:
        cells = "".join(
            f"<td class='num {'' if good is None else _cls(good(m))}'>{fmt(m)}</td>" for m in main.values())
        body += f"<tr><td>{label}</td>{cells}</tr>"
    return f"<div class='wrap'><table>{head}{body}</table></div>"


def _faults_table(faults: dict) -> str:
    head = ("<tr><th>Сбой</th>" + "".join(f"<th class='num'>{NAMES[k]}<br><span class='mute'>потеряно · дубли · p95</span></th>"
                                         for k in ("naive", "queue", "prod")) + "</tr>")
    body = ""
    for p in faults.values():
        cells = ""
        for k in ("naive", "queue", "prod"):
            m = p["configs"][k]
            cells += (f"<td class='num'><span class='{_cls(m['lost'] == 0)}'>{_n(m['lost'])}</span> · "
                      f"<span class='{_cls(m['dup_tasks'] == 0)}'>{_n(m['dup_tasks'])}</span> · {_sec(m['p95'])}</td>")
        body += f"<tr><td>{escape(p['title'])}</td>{cells}</tr>"
    return f"<div class='wrap'><table>{head}{body}</table></div>"


def _nights_table(nights: dict) -> str:
    s = nights["summary"]
    rows = [
        ("Ночей с потерями", lambda k: f"{s[k]['nights_with_lost']} из {nights['n']}"),
        ("Потеряно за ночь: медиана (мин–макс)",
         lambda k: f"{_n(s[k]['lost']['median'])} ({_n(s[k]['lost']['min'])}–{_n(s[k]['lost']['max'])})"),
        ("Ночей с дублями", lambda k: f"{s[k]['nights_with_dup']} из {nights['n']}"),
        ("Дублей за ночь: медиана (мин–макс)",
         lambda k: f"{_n(s[k]['dup_tasks']['median'])} ({_n(s[k]['dup_tasks']['min'])}–{_n(s[k]['dup_tasks']['max'])})"),
        ("В dead-letter за ночь: медиана (мин–макс)",
         lambda k: f"{_n(s[k]['dead']['median'])} ({_n(s[k]['dead']['min'])}–{_n(s[k]['dead']['max'])})"),
        ("Ночей, где задача исчерпала попытки", lambda k: f"{s[k]['nights_with_exhausted']} из {nights['n']}"),
        ("p95 до ответа: медиана по ночам", lambda k: _sec(s[k]["p95"]["median"])),
        ("Оборванных трасс за ночь: макс", lambda k: _n(s[k]["trace_incomplete"]["max"])),
    ]
    head = "<tr><th></th>" + "".join(f"<th class='num'>{NAMES[k]}</th>" for k in s) + "</tr>"
    body = "".join(f"<tr><td>{label}</td>" + "".join(f"<td class='num'>{fmt(k)}</td>" for k in s) + "</tr>"
                   for label, fmt in rows)
    return f"<div class='wrap'><table>{head}{body}</table></div>"


def _trace_table(events: list[dict], t0: float) -> str:
    body = ""
    for e in events:
        what = EVENTS.get(e["event"], e["event"])
        detail = []
        if e["event"] == "call":
            detail.append(f"{e['step']} · {e['kind']}")
            if e.get("tokens_in"):
                detail.append(f"{_n(e['tokens_in'])}+{_n(e['tokens_out'])} ток. · ${e['cost_usd']:.4f}")
            what = f"вызов модели: {e['step']}"
            cls = "ok" if e["kind"] == "ok" else "bad"
        else:
            cls = {"send": "ok", "done": "ok", "send_deduped": "ok", "lease_expired": "bad", "dead": "bad",
                   "request_error": "bad", "retry_scheduled": "bad", "client_timeout": "bad"}.get(e["event"], "")
        if e.get("error"):
            detail.append(e["error"])
        if e.get("delay_s") is not None:
            detail.append(f"через {_n(e['delay_s'], 1)} с")
        who = e.get("exec") or ""
        body += (f"<tr><td class='num'>+{_n(e['t'] - t0, 1)} с</td><td class='ev'>{escape(who)}</td>"
                 f"<td class='{cls}'>{escape(what)}</td><td class='ev mute'>{escape(' · '.join(detail))}</td></tr>")
    return ("<div class='wrap'><table><tr><th class='num'>время</th><th>попытка</th><th>событие</th><th>детали</th></tr>"
            f"{body}</table></div>")


def render_report(ref: dict) -> str:
    meta, night = ref["meta"], ref["meta"]["night"]
    f = night["faults"]
    main = ref["main"]
    p = [f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Разбор 07 · агент 24/7</title><style>{CSS}</style></head><body>",
         "<h1>Агент 24/7: одна ночь, три конфигурации</h1>",
         f"<p class='meta'>Прогон {escape(meta['run_at'])} · seed {meta['main_seed']} · без LLM: "
         f"{escape(meta['llm'])} · время виртуальное</p>"]
    # --- вход
    p.append("<section id='night'><h2>Ночь</h2><div class='cards'>")
    cards = [
        (_n(night["tasks"]), f"вопросов магазинов за {_n(night['hours'])} ч, из них "
                             f"{_n(night['peak_share'] * 100)} % — в утренний пик за {_n(night['peak_len'] / 60)} мин"),
        (f"{_n(f['rpm_limit'])} в минуту", "лимит запросов к модели на ключ; сверх — 429 с retry-after"),
        (f"{_n(f['p_overload'] * 100, 1)} · {_n(f['p_hang'] * 100, 1)} · {_n(f['p_drop'] * 100, 1)} %",
         "вызовов: перегрузка 529 · зависание · обрыв посреди ответа"),
        (f"раз в {_n(night['crash_every'] / 60)} мин", "kill -9 процесса с агентом, в среднем; подъём за "
                                                     f"{_n(night['restart_delay'])} с"),
        (f"{_n(night['p_lost_response'] * 100, 1)} %", "ответов API теряется в сети — клиент переспрашивает"),
        (f"{_n(f['p_poison'] * 100, 1)} %", "битых задач: модель отвечает 400 на каждый вызов"),
    ]
    p += [f"<div class='card'><b>{v}</b><span>{escape(t)}</span></div>" for v, t in cards]
    p.append("</div><p>Агент на задачу: три вызова модели (план и SQL, ответ с вызовом send_reply, итог), "
             "запрос в витрину и письмо магазину. Клиент — бот магазина: ждёт ответа API до "
             f"{_n(night['client_timeout'])} с и переспрашивает один раз.</p>")
    cfg_rows = "".join(
        f"<tr><td>{NAMES[k]}</td><td>{'очередь, ' + str(c['workers']) + ' воркера' if c['queue'] else 'синхронно в API'}</td>"
        f"<td class='num'>{_n(c['call_timeout'])} с</td><td>{'да' if c['queue'] else 'нет'}</td>"
        f"<td>{'да' if c['idempotent'] else 'нет'}</td></tr>"
        for k, c in meta["configs"].items())
    p.append("<div class='wrap'><table><tr><th>Конфигурация</th><th>Где работает агент</th><th class='num'>Таймаут вызова</th>"
             f"<th>Ретраи задачи и dead-letter</th><th>Ключ идемпотентности</th></tr>{cfg_rows}</table></div></section>")
    # --- итог
    p.append("<section id='result'><h2>Итог ночи</h2>")
    p.append(_main_table(main))
    p.append("<p class='meta'>Потеряно — ответа магазин не получил, и задачи нет в dead-letter: о ней никто не узнает. "
             "p50 и p95 — по доставленным ответам, от первого запроса клиента до письма.</p></section>")
    # --- сбои по одному
    p.append("<section id='faults'><h2>Сбои по одному</h2>")
    p.append(_faults_table(ref["faults"]))
    p.append("</section>")
    # --- ночи
    n = ref["nights"]
    p.append(f"<section id='nights'><h2>{n['n']} ночей с разными seed</h2>"
             f"<p class='meta'>seed {n['first_seed']}–{n['first_seed'] + n['n'] - 1}, по "
             f"{_n(n['tasks_per_night'])} задач, все сбои вместе.</p>")
    p.append(_nights_table(n))
    p.append("</section>")
    # --- трасса
    ex = ref["trace_example"]
    t0 = min(e["t"] for evs in ex["configs"].values() for e in evs)
    p.append(f"<section id='trace'><h2>Трасса одной задачи: {escape(ex['task'])}</h2>")
    for k in ("prod", "naive"):
        p.append(f"<div id='trace-{k}'><h3>{NAMES[k]}: {escape(ex['task'])}</h3>")
        p.append(_trace_table(ex["configs"][k], t0) + "</div>")
    p.append("</section></body></html>")
    return "".join(p)
