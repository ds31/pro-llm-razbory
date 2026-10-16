"""HTML-отчёт: три экрана для статьи — #tools (вход), #search (живой поиск и фильтр), #audit (аудит каталога).

Без внешних ресурсов: шрифты Onest / JetBrains Mono берутся, если установлены, иначе системные.
"""
from __future__ import annotations

import json
from html import escape

from .mcp import TOOL_GROUPS

CSS = """
:root{--paper:#f7f5ee;--ink:#14181d;--accent:#0b7d4f;--accent-soft:#dcefe5;--muted:#5d636b;--line:#dcd8cc;
--card:#fffdf8;--cut:#b4432f;--cut-soft:#f5e1dc;--mark:#e3f2e9}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 "Onest",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.mono,pre,code{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.page{max-width:1120px;margin:0 auto;padding:24px 16px 48px}
header.top{display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap;
border-bottom:2px solid var(--ink);padding-bottom:12px}
header.top h1{font-size:28px;font-weight:600;margin:0;letter-spacing:-.01em}
.kicker{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
nav a{color:var(--ink);margin-left:14px;font-size:14px}
section.screen{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:28px 28px 24px;margin:28px 0}
.screen-label{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);font-weight:600}
h2{font-size:26px;font-weight:600;margin:4px 0 6px;letter-spacing:-.01em}
h3{font-size:16px;font-weight:600;margin:22px 0 10px}
.lead{color:var(--muted);margin:0 0 18px;max-width:780px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:22px}
.grid2>*,.effect>*{min-width:0}
pre.card{white-space:pre-wrap;word-break:break-word}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
.group{margin-bottom:12px}.group b{display:block;font-size:13px;color:var(--muted);font-weight:500;margin-bottom:4px}
.chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 10px;margin:0 6px 6px 0;
font-size:13px;background:#fff}
.chip.ro{border-color:var(--accent);color:var(--accent)}
.chip.act{border-color:var(--ink)}
.chip.f{background:var(--accent-soft);border-color:transparent;color:#0a5a3a}
.legend{font-size:12px;color:var(--muted)}
pre{background:#14181d;color:#e9e6dc;border-radius:10px;padding:14px 16px;font-size:12.5px;line-height:1.55;
overflow-x:auto;margin:0;white-space:pre}
pre .k{color:#9fd8bb}pre .hl{background:#0b7d4f;color:#fff;border-radius:3px;padding:0 2px}
pre .miss{color:#f0a38f}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 4px}
.stat{border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:150px;background:#fff}
.stat .n{font-size:30px;font-weight:600;line-height:1.1}.stat .t{font-size:13px;color:var(--muted)}
.stat.accent .n{color:var(--accent)}.stat.cut .n{color:var(--cut)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
th{font-weight:500;color:var(--muted);font-size:12.5px}
td.num{font-family:"JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;text-align:right;white-space:nowrap}
.no{color:var(--cut)}.yes{color:var(--accent)}
.wrap{overflow-x:auto}
.dots{display:grid;grid-template-columns:repeat(25,minmax(0,1fr));gap:3px;margin:8px 0;max-width:470px}
.dot{aspect-ratio:1;border-radius:3px;background:#e6e2d6}
.dot.ok{background:var(--accent)}.dot.keep{background:var(--ink)}
.effect{display:grid;grid-template-columns:1fr 1fr;gap:22px;align-items:start}
@media(max-width:860px){.effect{grid-template-columns:1fr}}
.big{font-size:44px;font-weight:600;line-height:1}.big small{font-size:18px;color:var(--muted);font-weight:500}
.bar{position:relative;height:22px;background:var(--cut-soft);border-radius:6px;overflow:hidden;min-width:60px}
.bar span{position:absolute;left:0;top:0;bottom:0;background:var(--accent)}
.hbar{height:12px;background:var(--accent);border-radius:3px}
.hbar.cut{background:var(--cut)}
.scen td{vertical-align:middle}
.steps .chip{font-size:12px;padding:1px 8px}
.steps .chip.cut{border-color:var(--cut);color:var(--cut);background:var(--cut-soft)}
.note{font-size:13px;color:var(--muted)}
footer{font-size:13px;color:var(--muted);margin-top:28px}
"""


def _e(value) -> str:
    return escape(str(value))


def _money(price: dict | None) -> str:
    if not price:
        return "—"
    return f"{price.get('amount', 0) / 100:,.2f} {price.get('currency', '')}".replace(",", " ")


# --- экран (а): инструменты и запрос --------------------------------------------

def _tools_screen(s: dict) -> str:
    names = s["tool_names"]
    ro = set(s["read_only"])
    known = {n for _, group in TOOL_GROUPS for n in group}
    groups = [(title, [n for n in group if n in names]) for title, group in TOOL_GROUPS]
    other = [n for n in names if n not in known]
    if other:
        groups.append(("Прочее", other))
    blocks = "".join(
        f'<div class="group"><b>{_e(title)}</b>' + "".join(
            f'<span class="chip {"ro" if n in ro else "act"} mono">{_e(n)}</span>' for n in group) + "</div>"
        for title, group in groups if group)
    req = s["request"]
    head = "\n".join(f"{k}: {v}" for k, v in req["headers"].items())
    body = json.dumps(req["body"], ensure_ascii=False, indent=2)
    body_html = _e(body).replace("&quot;filters&quot;", '<span class="hl">&quot;filters&quot;</span>')
    filters = "".join(f'<span class="chip f mono">{_e(f)}</span>' for f in s["search_filters"])
    attrs = ", ".join(s["attribute_filters"])
    source = "живой ответ" if s["source"] == "live" else "снимок"
    return f"""
<section class="screen" id="tools">
  <div class="screen-label">Экран 1 · Вход</div>
  <h2>Что получает агент: {s['tools']} инструментов Shop MCP</h2>
  <p class="lead">Один адрес — <span class="mono">{_e(s['endpoint'])}</span>, протокол MCP {_e(s['protocol'])} без сессии.
  Любой MCP-агент ищет по каталогу, собирает корзину и оформляет оплату. Источник: {source} от {_e(s['captured'])}.</p>
  <div class="grid2">
    <div>
      <h3>Инструменты</h3>{blocks}
      <p class="legend"><span class="chip ro">чтение</span><span class="chip act">действие</span> — по аннотации readOnlyHint</p>
      <h3>Жёсткие фильтры search_catalog</h3>
      <div>{filters}</div>
      <p class="note">Атрибуты, по которым фильтр работает жёстко: <b class="mono">{_e(attrs)}</b>.
      «Context soft; filters hard» — так инструмент описан для агента.</p>
    </div>
    <div>
      <h3>Запрос агента: «{_e(s['query'])}», мужские</h3>
      <pre>POST {_e(s['endpoint'])}
{_e(head)}

{body_html}</pre>
    </div>
  </div>
</section>"""


# --- экран (б): живой поиск и фильтр --------------------------------------------

HL_KEYS = {"options", "rating", "price", "availability", "tech_specs"}
EXPECTED = ["options", "rating", "metadata"]


def _trim(p: dict) -> dict:
    out: dict = {"title": p.get("title")}
    if p.get("rating"):
        out["rating"] = {k: p["rating"][k] for k in ("value", "count") if k in p["rating"]}
    if p.get("options"):
        out["options"] = [{"name": o["name"], "values": [v.get("label") for v in o.get("values", [])][:4]}
                          for o in p["options"]]
    if p.get("metadata"):
        out["metadata"] = {"tech_specs": [x if len(x) <= 60 else x[:57] + "…"
                                          for x in (p["metadata"].get("tech_specs") or [])[:3]]}
    v = (p.get("variants") or [{}])[0]
    var = {k: v[k] for k in ("price", "availability") if k in v}
    if v.get("rating"):
        var["rating"] = {k: v["rating"][k] for k in ("value", "count") if k in v["rating"]}
    if v.get("seller"):
        var["seller"] = {"name": v["seller"].get("name")}
    out["variants"] = [var]
    return out


def _json_html(obj, depth: int = 0, missing: dict | None = None) -> str:
    pad = "  " * depth
    if isinstance(obj, dict):
        lines = []
        items = list(obj.items())
        for i, (k, v) in enumerate(items):
            comma = "," if i < len(items) - 1 or (missing and missing.get(depth)) else ""
            sub = _json_html(v, depth + 1, missing if k == "variants" else None)
            key = f'<span class="k">&quot;{_e(k)}&quot;</span>'
            if k in HL_KEYS:
                key = f'<span class="hl">&quot;{_e(k)}&quot;</span>'
            lines.append(f"{pad}  {key}: {sub.lstrip()}{comma}")
        for name in (missing or {}).get(depth, []):
            lines.append(f'{pad}  <span class="miss">// нет поля {_e(name)} — фильтр агента его не найдёт</span>')
        return f"{pad}{{\n" + "\n".join(lines) + f"\n{pad}}}"
    if isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            return pad + _e(json.dumps(obj, ensure_ascii=False))
        inner = ",\n".join(_json_html(x, depth + 1, missing) for x in obj)
        return f"{pad}[\n{inner}\n{pad}]"
    return pad + _e(json.dumps(obj, ensure_ascii=False))


def _example(p: dict) -> str:
    t = _trim(p)
    miss_top = [k for k in EXPECTED if k not in t]
    v = t["variants"][0]
    miss_var = [] if "rating" in v else ["rating"]
    # depth 0 — товар, depth 2 — вариант внутри списка variants
    return _json_html(t, 0, {0: miss_top, 2: miss_var})


def _richness(p: dict) -> int:
    v = (p.get("variants") or [{}])[0]
    return sum(bool(x) for x in (p.get("options"), p.get("metadata"), p.get("rating"), v.get("rating")))


def _dots(products: list[dict], ok, keep=frozenset()) -> str:
    cells = []
    for p in products:
        cls = "keep" if p["id"] in keep else ("ok" if ok(p) else "")
        cells.append(f'<div class="dot {cls}" title="{_e(p.get("title", ""))}"></div>')
    return f'<div class="dots">{"".join(cells)}</div>'


def _search_screen(s: dict, payloads: dict) -> str:
    from .mcp import rating_ok
    products = payloads["search"].get("products", [])
    rows = []
    for p in products:
        v = (p.get("variants") or [{}])[0]
        r = v.get("rating") or {}
        rating = f'{r["value"]:g} · {r["count"]} отз.' if r else '<span class="no">нет</span>'
        opts = ", ".join(o["name"] for o in p.get("options") or []) or '<span class="no">нет</span>'
        specs = '<span class="yes">есть</span>' if (p.get("metadata") or {}).get("tech_specs") else '<span class="no">нет</span>'
        avail = (v.get("availability") or {}).get("available")
        rows.append(f"<tr><td>{_e(p.get('title', ''))}</td><td class=\"num\">{_e(_money(v.get('price')))}</td>"
                    f"<td>{rating}</td><td>{opts if opts.startswith('<') else _e(opts)}</td><td>{specs}</td>"
                    f"<td>{'да' if avail else '<span class=no>нет</span>'}</td></tr>")
    examples = ""
    if products:
        full = max(products, key=_richness)
        thin = min(products, key=_richness)
        examples = f"""
  <h3>Две карточки из одной выдачи: подсвечены поля, по которым фильтрует агент</h3>
  <div class="grid2">
    <div><p class="note">Полная карточка</p><pre class="card">{_example(full)}</pre></div>
    <div><p class="note">Карточка с пустыми полями</p><pre class="card">{_example(thin)}</pre></div>
  </div>"""
    e = s["filter_effect"]
    r = s["rating_filter"]["rating"]["variant"]
    ok = lambda p: rating_ok(p, r["min"], r["min_count"])  # noqa: E731
    base = payloads["search-base"].get("products", [])
    filt = payloads["search-filtered"].get("products", [])
    keep = {p["id"] for p in base} & {p["id"] for p in filt}
    fields = {f["field"]: f for f in s["card_fields"]}
    key_fields = [("options[Color]", "Цвет как опция варианта"), ("variants[].rating", "Рейтинг варианта (для фильтра)"),
                  ("rating", "Рейтинг товара"), ("metadata.tech_specs", "Характеристики"),
                  ("options", "Опции вообще"), ("variants[].availability", "Наличие"), ("variants[].price", "Цена с валютой")]
    cov = "".join(
        f'<tr><td>{_e(label)} <span class="note mono">{_e(k)}</span></td>'
        f'<td class="num">{fields.get(k, {"present": 0})["present"]} из {s["products"]}</td>'
        f'<td style="width:40%"><div class="hbar" style="width:{100 * fields.get(k, {"present": 0})["present"] / max(s["products"], 1):.0f}%"></div></td></tr>'
        for k, label in key_fields)
    size_names = [f["field"][8:-1] for f in s["card_fields"] if f["field"].startswith("options[")
                  and any(w in f["field"].lower() for w in ("size", "pointure", "fit"))]
    return f"""
<section class="screen" id="search">
  <div class="screen-label">Экран 2 · Ключевой шаг</div>
  <h2>Живой поиск: что агент видит в карточке</h2>
  <p class="lead">search_catalog вернул {s['products']} товаров (из ~{_e(s['total_count'])} найденных), формат UCP {_e(s['ucp_version'])}.
  Агент выбирает не по картинке, а по полям: опции, рейтинг с числом отзывов, цена с валютой, наличие, характеристики.</p>
  <div class="wrap"><table>
    <tr><th>Товар</th><th>Цена</th><th>Рейтинг варианта</th><th>Опции</th><th>Характеристики</th><th>В наличии</th></tr>
    {''.join(rows)}
  </table></div>
  <h3>Сколько карточек в выдаче заполнили поле</h3>
  <div class="wrap"><table>{cov}</table></div>
  <p class="note">Размер в одной выдаче назван по-разному: <span class="mono">{_e(', '.join(size_names) or '—')}</span>.
  Жёсткий фильтр принимает одно имя — <span class="mono">Size</span>.</p>
  {examples}
  <h3>Жёсткий фильтр: тот же запрос, {e['base']} товаров, плюс <span class="mono">rating.variant {{min: {r['min']:g}, min_count: {r['min_count']}}}</span></h3>
  <div class="effect">
    <div>
      <div class="big">{e['base_meeting']} из {e['base']}</div><p class="note">товаров выдачи без фильтра проходят фильтр</p>
      {_dots(base, ok)}
      <p class="note">Зелёные — у варианта рейтинг от {r['min']:g} при {r['min_count']}+ отзывах. Серые — рейтинга нет
      или отзывов меньше {r['min_count']}: агент с этим фильтром их не увидит ({e['base_dropped']} из {e['base']}).</p>
    </div>
    <div>
      <div class="big">{e['replaced']} из {e['filtered']}</div><p class="note">в выдаче с фильтром — другие товары</p>
      {_dots(filt, ok, keep)}
      <p class="note">Чёрные — товары, которые были и в выдаче без фильтра ({e['overlap']}).
      Все {e['filtered_meeting']} из {e['filtered']} проходят фильтр: выдачу заняли карточки, где рейтинг и число отзывов заполнены.</p>
    </div>
  </div>
</section>"""


# --- экран (в): аудит каталога --------------------------------------------------

def _audit_screen(audit: dict, rules: dict | None) -> str:
    a = audit["summary"]
    rd = a["readiness"]
    stats = f"""
  <div class="stats">
    <div class="stat"><div class="n">{a['cards']}</div><div class="t">карточек в каталоге</div></div>
    <div class="stat"><div class="n">{rd['mean']:g}</div><div class="t">средний балл готовности из 100</div></div>
    <div class="stat accent"><div class="n">{a['visible_total']} из {a['pool_total']}</div><div class="t">подходящих товаров агент покажет</div></div>
    <div class="stat cut"><div class="n">{a['lost_cards']}</div><div class="t">карточек агент не увидит хотя бы в одном сценарии</div></div>
    <div class="stat accent"><div class="n">{a['fixable_1_2']}</div><div class="t">из них чинятся 1–2 полями из учётной системы</div></div>
  </div>"""
    srows = []
    for sc in a["scenarios"]:
        pct = 100 * sc["visible"] / sc["pool"] if sc["pool"] else 0
        steps = "".join(f'<span class="chip {"cut" if f["cut"] else ""}">{_e(f["label"])}{" −" + str(f["cut"]) if f["cut"] else ""}</span>'
                        for f in sc["funnel"])
        srows.append(f"""<tr class="scen"><td class="mono">{_e(sc['id'])}</td><td>{_e(sc['title'])}<div class="steps">{steps}</div></td>
<td class="num">{sc['visible']} из {sc['pool']}</td><td style="width:22%"><div class="bar"><span style="width:{pct:.0f}%"></span></div></td></tr>""")
    top_max = max([b["hits"] for b in a["top_blockers"]] + [1])
    blockers = "".join(f'<tr><td>{_e(b["label"])} <span class="note mono">{_e(b["field"])}</span></td><td class="num">{b["hits"]}</td>'
                       f'<td style="width:45%"><div class="hbar cut" style="width:{100 * b["hits"] / top_max:.0f}%"></div></td></tr>'
                       for b in a["top_blockers"])
    fx = a["fixable"]
    worst = sorted(audit["cards"], key=lambda c: (c["score"], c["sku"]))[:8]
    worst_rows = "".join(f'<tr><td class="mono">{_e(c["sku"])}</td><td>{_e(c["title"])}</td><td class="num">{c["score"]}</td>'
                         f'<td>{_e(", ".join(c["missing"][:4]))}</td></tr>' for c in worst)
    rules_rows = ""
    if rules:
        rules_rows = "".join(f'<tr><td>{_e(r["label"])}</td><td class="mono">{_e(r["shop_mcp"])}</td><td class="num">{r["weight"]}</td></tr>'
                             for r in rules["rules"])
        rules_rows = f'<h3>Правила аудита → поле или фильтр Shop MCP</h3><div class="wrap"><table><tr><th>Поле карточки</th><th>Что отражает в Shop MCP</th><th>Вес</th></tr>{rules_rows}</table></div>'
    return f"""
<section class="screen" id="audit">
  <div class="screen-label">Экран 3 · Результат</div>
  <h2>Аудит каталога: кого агент не увидит и почему</h2>
  <p class="lead">Вымышленная сеть, {a['cards']} карточек одежды, обуви и товаров для дома (синтетика). Пять покупателей
  с жёсткими фильтрами в форме Shop MCP. «Подходящие» — товары, которые покупателю реально подходят по данным учётной системы;
  агент видит только карточку.</p>
  {stats}
  <h3>Пять покупателей: сколько подходящих товаров агент покажет</h3>
  <div class="wrap"><table>
    <tr><th></th><th>Запрос и шаги фильтра (−N — где отсеклись)</th><th>Покажет</th><th></th></tr>
    {''.join(srows)}
  </table></div>
  <div class="grid2">
    <div>
      <h3>Топ-5 полей, из-за которых агент проходит мимо</h3>
      <div class="wrap"><table>{blockers}</table></div>
      <p class="note">Считается по парам «сценарий × потерянная карточка»: какое поле нужно заполнить, чтобы она прошла.</p>
    </div>
    <div>
      <h3>Сколько полей заполнить, чтобы карточку снова увидели</h3>
      <div class="stats">
        <div class="stat accent"><div class="n">{fx['1']}</div><div class="t">одно поле</div></div>
        <div class="stat accent"><div class="n">{fx['2']}</div><div class="t">два поля</div></div>
        <div class="stat"><div class="n">{fx['3+']}</div><div class="t">три и больше</div></div>
      </div>
      <p class="note">Все значения уже есть в учётной системе — их просто не выгрузили в карточку.</p>
    </div>
  </div>
  <h3>Самые слабые карточки по баллу готовности</h3>
  <div class="wrap"><table><tr><th>SKU</th><th>Товар</th><th>Балл</th><th>Чего не хватает</th></tr>{worst_rows}</table></div>
  {rules_rows}
</section>"""


def render_report(probe: dict, payloads: dict, audit: dict, rules: dict | None = None) -> str:
    source = "живой Shop MCP" if probe["source"] == "live" else f"снимок Shop MCP от {probe['captured']}"
    note = f'<p class="note">{_e(probe["note"])}</p>' if probe.get("note") else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Агент выбирает карточку</title><style>{CSS}</style></head><body><div class="page">
<header class="top"><div><div class="kicker">Разбор 02 · Как читать AI · pro-llm.ru</div>
<h1>Агент покупает в чате — кого он выберет?</h1></div>
<nav><a href="#tools">Вход</a><a href="#search">Поиск и фильтр</a><a href="#audit">Аудит</a></nav></header>
<p class="note">Источник probe: {_e(source)}. Каталог для аудита — синтетический.</p>{note}
{_tools_screen(probe)}
{_search_screen(probe, payloads)}
{_audit_screen(audit, rules)}
<footer>Пакет «применить у себя»: github.com/ds31/pro-llm-razbory, папка 02-agent-vybiraet-kartochku. Код — MIT, тексты — CC BY 4.0.
Ответы Shop MCP обезличены: магазины заменены на merchant-NN.example.</footer>
</div></body></html>"""
