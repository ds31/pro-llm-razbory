"""Аудит готовности карточек для агента: правила (audit/rules.yaml) и сценарии покупателей (eval/scenarios.yaml).

Две проверки:
- балл готовности 0–100 по правилам — без привязки к запросу, «насколько карточка вообще пригодна агенту»;
- сценарии — жёсткие фильтры агента в форме Shop MCP. Пул — товары, которые покупателю реально подходят
  (по учётной системе), видимые — те, чьи карточки проходят все фильтры.
"""
from __future__ import annotations

import statistics
from pathlib import Path

import yaml

from .synth import gtin_ok

FIELD_LABELS = {
    "color": "Цвет", "sizes": "Размер", "target_gender": "Пол", "gtin": "GTIN", "price": "Цена",
    "currency": "Валюта цены", "available": "Наличие", "ships_to": "Страны доставки",
    "delivery_days": "Срок доставки", "rating": "Рейтинг", "rating_count": "Число отзывов",
    "tech_specs": "Характеристики", "title": "Название", "description": "Описание", "image_alt": "Подпись фото",
}
ATTR_FIELDS = {"Color": "color", "Size": "sizes", "Target gender": "target_gender"}
ATTR_LABELS = {"Color": "Цвет", "Size": "Размер", "Target gender": "Пол"}
VERIFY_FIELDS = ["title", "description", "tech_specs"]


def load_rules(path: Path | str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_scenarios(path: Path | str) -> list[dict]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["scenarios"]


def _list(value: str) -> list[str]:
    return [x.strip() for x in value.split(";") if x.strip()]


def _num(value: str) -> float | None:
    try:
        return float(value.replace(",", "."))
    except (AttributeError, ValueError):
        return None


# --- правила готовности ------------------------------------------------------

def check_rule(rule: dict, card: dict, cfg: dict) -> bool:
    kind = rule["check"]
    value = card.get(rule["field"], "") if isinstance(rule["field"], str) else None
    if kind == "filled":
        return bool(value.strip())
    if kind == "one_of":
        return value in rule["values"]
    if kind == "gtin":
        return gtin_ok(value)
    if kind == "min_items":
        return len(_list(value)) >= rule["min"]
    if kind == "min_len":
        return len(value.strip()) >= rule["min"]
    if kind == "price_currency":
        price = _num(card.get("price", ""))
        cur = card.get("currency", "")
        return price is not None and price > 0 and len(cur) == 3 and cur.isalpha() and cur.isupper()
    if kind == "rating_count":
        count = _num(card.get("rating_count", ""))
        return _num(card.get("rating", "")) is not None and count is not None and count >= cfg["min_review_count"]
    raise ValueError(f"неизвестная проверка: {kind}")


def readiness(card: dict, cfg: dict) -> tuple[int, list[dict]]:
    """Балл 0–100 и непройденные правила по убыванию веса."""
    rules = [r for r in cfg["rules"] if card.get("category") in r["applies_to"]]
    failed = [r for r in rules if not check_rule(r, card, cfg)]
    total = sum(r["weight"] for r in rules)
    lost = sum(r["weight"] for r in failed)
    score = round(100 * (total - lost) / total) if total else 0
    return score, sorted(failed, key=lambda r: -r["weight"])


# --- сценарии: фильтры агента ------------------------------------------------

def scenario_steps(s: dict) -> list[tuple[str, str, list[str]]]:
    """Шаги фильтра в порядке воронки: (id, подпись, поля карточки)."""
    f = s.get("filters", {})
    steps = []
    if s.get("lookup") == "gtin":
        steps.append(("lookup", "Поиск по штрихкоду (lookup_catalog)", ["gtin"]))
    for a in f.get("attributes", []):
        steps.append((f"attr:{a['name']}", f"{ATTR_LABELS[a['name']]} = {', '.join(a['values'])} ({a['name']})",
                      [ATTR_FIELDS[a["name"]]]))
    if "price" in f:
        steps.append(("price", f"Цена до {f['price']['max']:,} ₽".replace(",", " "), ["price", "currency"]))
    if "ships_to" in f:
        steps.append(("ships_to", f"Доставка в страну покупателя ({f['ships_to']['country']})", ["ships_to"]))
    if f.get("available"):
        steps.append(("available", "В наличии (available)", ["available"]))
    if "rating" in f:
        r = f["rating"]["variant"]
        steps.append(("rating", f"Рейтинг от {r['min']:g} при {r['min_count']}+ отзывах", ["rating", "rating_count"]))
    if s.get("must_mention"):
        steps.append(("verify", f"Проверка по тексту: «{s['query']}»", VERIFY_FIELDS))
    return steps


def step_passes(step: str, s: dict, row: dict) -> bool:
    f = s.get("filters", {})
    if step == "lookup":
        return gtin_ok(row.get("gtin", ""))
    if step.startswith("attr:"):
        name = step[5:]
        wanted = next(a["values"] for a in f["attributes"] if a["name"] == name)
        have = _list(row.get(ATTR_FIELDS[name], ""))
        return any(v in have for v in wanted)
    if step == "price":
        price = _num(row.get("price", ""))
        return price is not None and row.get("currency") == f["price"]["currency"] and price <= f["price"]["max"]
    if step == "ships_to":
        return f["ships_to"]["country"] in _list(row.get("ships_to", ""))
    if step == "available":
        return row.get("available") == "true"
    if step == "rating":
        r = f["rating"]["variant"]
        value, count = _num(row.get("rating", "")), _num(row.get("rating_count", ""))
        return value is not None and count is not None and value >= r["min"] and count >= r["min_count"]
    if step == "verify":
        text = " ".join(row.get(c, "") for c in VERIFY_FIELDS).lower()
        return any(w.lower() in text for w in s["must_mention"])
    raise ValueError(f"неизвестный шаг: {step}")


def _pool_keys_match(s: dict, row: dict) -> bool:
    return all(row.get(k) == v for k, v in s.get("pool", {}).items())


def in_pool(s: dict, erp_row: dict) -> bool:
    """Товар реально подходит покупателю: по данным учётной системы проходит все фильтры."""
    return _pool_keys_match(s, erp_row) and all(step_passes(st, s, erp_row) for st, *_ in scenario_steps(s))


def blame(step: str, s: dict, card: dict, erp_row: dict | None) -> list[str]:
    """Поля карточки, из-за которых шаг не пройден: отличаются от учётной системы, а без неё — пустые."""
    fields = next(fs for st, _, fs in scenario_steps(s) if st == step)
    if erp_row is None:
        return [c for c in fields if not card.get(c, "").strip()]
    return [c for c in fields if card.get(c, "") != erp_row.get(c, "")]


def evaluate(s: dict, cards: list[dict], erp: list[dict] | None) -> dict:
    steps = scenario_steps(s)
    if erp is not None:
        by_sku = {c["sku"]: c for c in cards}
        pool = [(by_sku[e["sku"]], e) for e in erp if in_pool(s, e) and e["sku"] in by_sku]
    else:
        pool = [(c, None) for c in cards if _pool_keys_match(s, c)]
    funnel = {st: 0 for st, *_ in steps}
    independent = {st: 0 for st, *_ in steps}
    visible, lost = [], []
    for card, truth in pool:
        failed = [st for st, *_ in steps if not step_passes(st, s, card)]
        for st in failed:
            independent[st] += 1
        if not failed:
            visible.append(card["sku"])
            continue
        funnel[failed[0]] += 1
        fields: list[str] = []
        for st in failed:
            fields += [c for c in blame(st, s, card, truth) if c not in fields]
        lost.append({"sku": card["sku"], "title": card["title"], "failed": failed, "fields": fields})
    fixable = {"1": 0, "2": 0, "3+": 0}
    for x in lost:
        n = len(x["fields"])
        if n:
            fixable["1" if n == 1 else "2" if n == 2 else "3+"] += 1
    n_pool = len(pool)
    return {
        "id": s["id"], "title": s["title"], "tool": s.get("tool", "search_catalog"), "filters": s.get("filters", {}),
        "pool": n_pool, "visible": len(visible),
        "visible_pct": round(100 * len(visible) / n_pool, 1) if n_pool else 0.0,
        "funnel": [{"step": st, "label": label, "cut": funnel[st]} for st, label, _ in steps],
        "cut_independent": independent, "fixable": fixable, "lost": lost, "visible_skus": visible,
    }


def run_audit(cards: list[dict], erp: list[dict] | None, cfg: dict, scenarios: list[dict]) -> dict:
    """Итог аудита: summary (цифры статьи), scenarios (с потерянными карточками) и таблица по карточкам."""
    rows = []
    rule_fails: dict[str, int] = {}
    for c in cards:
        score, failed = readiness(c, cfg)
        for r in failed:
            rule_fails[r["id"]] = rule_fails.get(r["id"], 0) + 1
        rows.append({"sku": c["sku"], "title": c["title"], "category": c["category"], "score": score,
                     "missing": [r["label"] for r in failed]})
    results = [evaluate(s, cards, erp) for s in scenarios]
    hits: dict[str, int] = {}
    per_card: dict[str, list[str]] = {}
    for r in results:
        for x in r["lost"]:
            for f in x["fields"]:
                hits[f] = hits.get(f, 0) + 1
            acc = per_card.setdefault(x["sku"], [])
            acc += [f for f in x["fields"] if f not in acc]
    for row in rows:
        row["lost_in"] = [r["id"] for r in results if any(x["sku"] == row["sku"] for x in r["lost"])]
        row["visible_in"] = [r["id"] for r in results if row["sku"] in r["visible_skus"]]
    fixable = {"1": 0, "2": 0, "3+": 0}
    for fields in per_card.values():
        n = len(fields)
        if n:
            fixable["1" if n == 1 else "2" if n == 2 else "3+"] += 1
    scores = [r["score"] for r in rows]
    top = sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    rule_labels = {r["id"]: r["label"] for r in cfg["rules"]}
    summary = {
        "cards": len(cards),
        "readiness": {
            "mean": round(statistics.mean(scores), 1), "median": statistics.median(scores),
            "ready_80plus": sum(s >= 80 for s in scores), "below_60": sum(s < 60 for s in scores),
            "rules_failed": [{"rule": k, "label": rule_labels[k], "cards": v}
                             for k, v in sorted(rule_fails.items(), key=lambda kv: (-kv[1], kv[0]))],
        },
        "scenarios": [{k: v for k, v in r.items() if k not in ("lost", "visible_skus", "filters")} for r in results],
        "pool_total": sum(r["pool"] for r in results),
        "visible_total": sum(r["visible"] for r in results),
        "top_blockers": [{"field": f, "label": FIELD_LABELS.get(f, f), "hits": n} for f, n in top],
        "lost_cards": len(per_card),
        "fixable": fixable,
        "fixable_1_2": fixable["1"] + fixable["2"],
    }
    return {"summary": summary, "scenarios": results, "cards": rows}
