"""Эксперимент: живой поток октября 2026 с дефектами через три конфигурации, детерминированно, без LLM.

- `run_scenario` — один сценарий: утро за утром грузит файлы во все конфигурации, ворота просят исправленные
  файлы, и в день, когда конфигурация объявляет октябрь закрытым, фиксирует выручку октября и ответы на вопросы.
- `showcase` — по одному дефекту в фиксированном месте (+ чистый поток и «всё сразу»).
- `random_runs` — N сценариев со случайными дефектами: доля пойманных, ложные срабатывания, день закрытия.
"""
from __future__ import annotations

import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import defects as D
from .feed import (FEED_SEED, MONTH, MONTH_END, SIM_END, SIM_START, FeedFiles, calendar_closed_through, days,
                   make_feed)
from .modes import MODES, Truth
from .questions import QUESTIONS, score

NOV1 = date(2026, 11, 1)
TOL_PCT = 0.5


@dataclass
class ModeOutcome:
    close_day: str | None = None                # утро, когда октябрь объявлен закрытым
    revenue_at_close: float | None = None       # выручка октября, которую конфигурация объявила окончательной
    revenue_final: float | None = None          # она же на утро 15.11
    error_pct: float | None = None              # ошибка объявленной выручки против правды
    rewritten: bool = False                     # закрытый октябрь поменялся задним числом
    correct_at_close: int | None = None         # верных из 9 в день закрытия
    wrong_at_close: list = field(default_factory=list)
    month_on_nov1: str = ""                     # какой месяц агент назвал «последним» утром 1.11
    correct_on_nov1: int = 0


@dataclass
class ScenarioResult:
    name: str
    seed: int
    truth_revenue: float
    modes: dict
    detection: list = field(default_factory=list)
    false_positives: dict = field(default_factory=dict)
    clean_files: int = 0
    clean_rows: int = 0
    timeline: list = field(default_factory=list)
    gate_log: dict = field(default_factory=dict)


def _pct(got, exp):
    if got is None or exp is None:
        return None
    return 100.0 * (got - exp) / exp


def run_scenario(base: Path | str, feed, injections: list, name: str = "",
                 keys=("raw", "rules01", "gate"), timeline: bool = False, until: date | None = None,
                 inspect=None) -> ScenarioResult:
    """until — остановиться после этого утра; inspect(modes) — заглянуть в базы до закрытия соединений."""
    with FeedFiles(feed) as ff:
        truth = Truth(base, ff)
        modes = {k: MODES[k](base, ff) for k in keys}
        try:
            res = _simulate(feed, injections, name, truth, modes, timeline, until or SIM_END)
            if inspect:
                inspect(modes)
            return res
        finally:
            truth.close()
            for m in modes.values():
                m.close()


def _simulate(feed, injections, name, truth, modes, timeline, until) -> ScenarioResult:
    due: dict = {}
    fixes: dict = {}
    for ld in feed.loads.values():
        if ld.on_request:
            fixes[(ld.kind, ld.store_id, ld.business_date)] = ld
        elif ld.received_on:
            due.setdefault(ld.received_on, []).append(ld.load_id)
    scheduled: dict = {}
    truth_oct = truth.revenue(MONTH)
    truth_ans = {MONTH_END: truth.answers(MONTH_END)}
    out = {k: ModeOutcome() for k in modes}
    tl = []
    for d in days(SIM_START, until):
        row = {"day": d.isoformat(), "modes": {}}
        for k, m in modes.items():
            ids = due.get(d, []) + (scheduled.get(d, []) if k == "gate" else [])
            res = m.ingest(d, ids)
            if k == "gate":
                for req in res.requests:
                    fx = fixes.get(req)
                    if fx:
                        scheduled.setdefault(d + timedelta(fx.lag), []).append(fx.load_id)
                row["gate"] = {"loads": res.loads, "accepted": res.accepted, "held": res.held,
                               "dropped": res.dropped, "released": res.released, "warnings": res.warnings,
                               "requests": [f"{r[0]} · магазин {r[1]} · {r[2]:%d.%m}" for r in res.requests],
                               "closures": [c.summary() for c in getattr(m, "closures", [])]}
                if timeline:
                    row["gate"]["violations"] = dict(m.con.execute(
                        "SELECT rule_id, count(*) FROM log.violations WHERE day = ? GROUP BY 1 ORDER BY 1", [d]).fetchall())
                    row["gate"]["missing"] = [f"магазин {s} · {b:%d.%m}" for s, b in m.con.execute(
                        "SELECT store_id, business_date FROM log.completeness WHERE day = ? ORDER BY 2, 1", [d]).fetchall()]
                    row["gate"]["held_total"] = m.con.execute(
                        "SELECT (SELECT count(*) FROM q.sales WHERE status = 'held') + "
                        "(SELECT count(*) FROM q.stock WHERE status = 'held')").fetchone()[0]
            ct = m.closed_through(d)
            o = out[k]
            need_mart = (o.close_day is None and ct >= MONTH_END) or d == NOV1 or timeline
            if need_mart:
                m.build_mart()
            if d == NOV1:
                if ct not in truth_ans:
                    truth_ans[ct] = truth.answers(ct)
                sc = score(m.answers(d), truth_ans[ct])
                o.month_on_nov1 = f"{ct:%Y-%m}"
                o.correct_on_nov1 = sum(sc.values())
            if o.close_day is None and ct >= MONTH_END:
                o.close_day = d.isoformat()
                o.revenue_at_close = m.revenue(d, MONTH)
                o.error_pct = _pct(o.revenue_at_close, truth_oct)
                sc = score(m.answers(d), truth_ans[MONTH_END])
                o.correct_at_close = sum(sc.values())
                o.wrong_at_close = [q for q, ok in sc.items() if not ok]
            if timeline:
                row["modes"][k] = {"closed_through": ct.isoformat(),
                                   "oct_revenue": m.revenue(d, MONTH) if ct >= MONTH_END else None}
        if timeline:
            tl.append(row)
    for k, m in modes.items():
        o = out[k]
        if o.close_day:
            m.build_mart()
            o.revenue_final = m.revenue(until, MONTH)
            o.rewritten = abs((o.revenue_final or 0) - (o.revenue_at_close or 0)) > 0.005
    res = ScenarioResult(name, feed.seed, truth_oct, {k: asdict(v) for k, v in out.items()}, timeline=tl)
    if "gate" in modes:
        _detection(res, modes["gate"].con, injections, feed)
        res.gate_log = _gate_log(modes["gate"].con)
    return res


def _detection(res: ScenarioResult, con, injections: list, feed) -> None:
    viol = con.execute("SELECT tbl, load_id, row_no, rule_id FROM log.violations WHERE load_id > 0").fetchall()
    compl = {(s, b) for s, b in con.execute("SELECT DISTINCT store_id, business_date FROM log.completeness").fetchall()}
    by_row: dict = {}
    by_load: dict = {}
    for tbl, lid, rn, rule in viol:
        if rn is None:
            by_load.setdefault(lid, set()).add(rule)
        else:
            by_row.setdefault((lid, rn), set()).add(rule)
    touched_rows, touched_loads, touched_parts = set(), set(), set()
    for inj in injections:
        touched_rows |= inj.rows
        touched_loads |= inj.loads | {lid for lid, _ in inj.rows}
        touched_parts |= inj.parts
    for inj in injections:
        hit: set = set()
        for key in inj.rows:
            hit |= by_row.get(key, set())
        for lid in inj.loads:
            hit |= by_load.get(lid, set())
        if inj.parts & compl:
            hit.add("C01")
        res.detection.append({"defect": inj.defect, "rule": inj.rule, "caught": inj.rule in hit,
                              "caught_any": bool(hit), "rules": sorted(hit)})
    fp: dict = {}
    # исправленный файл — часть своего дефекта: в нём могут быть строки других дефектов (новинка без карточки)
    fix_loads = {lid for inj in injections for lid in inj.fixes}
    for (lid, rn), rules in by_row.items():
        if (lid, rn) not in touched_rows and lid not in fix_loads:
            for r in rules:
                fp[r] = fp.get(r, 0) + 1
    for lid, rules in by_load.items():
        if lid not in touched_loads:
            for r in rules:
                fp[r] = fp.get(r, 0) + 1
    for p in compl - touched_parts:
        fp["C01"] = fp.get("C01", 0) + 1
    res.false_positives = fp
    clean = [ld for ld in feed.loads.values() if ld.kind in ("sales", "stock") and ld.load_id not in touched_loads
             and not ld.on_request]
    res.clean_files = len(clean)
    res.clean_rows = sum(len((feed.sales if ld.kind == "sales" else feed.stock)[ld.load_id]) for ld in clean)


def _gate_log(con) -> dict:
    q = con.execute("""SELECT 'продажи' AS kind, rules, status, count(*) FROM q.sales
                       WHERE load_id > 0 GROUP BY ALL
                       UNION ALL SELECT 'остатки', rules, status, count(*) FROM q.stock
                       WHERE load_id > 0 GROUP BY ALL
                       ORDER BY 1, 2, 3""").fetchall()
    req = con.execute("SELECT day, kind, store_id, business_date, rules FROM log.requests ORDER BY 1, 2, 3").fetchall()
    warn = con.execute("""SELECT rule_id, count(*) FROM log.violations
                          WHERE action = 'pass' AND load_id > 0 GROUP BY 1 ORDER BY 1""").fetchall()
    return {"quarantine": [list(map(str, r)) for r in q],
            "requests": [[r[0].isoformat(), r[1], r[2], r[3].isoformat(), r[4]] for r in req],
            "warnings": [list(map(str, r)) for r in warn]}


# --------------------------------------------------------------------------- витрина
SHOWCASE = ["clean", "scanner", "reload", "missing", "kopecks", "negative_stock", "future_date", "unknown_sku",
            "dup_card", "truncated", "all"]


def showcase_feed(base, defect: str):
    feed = make_feed(base, FEED_SEED)
    if defect == "all":
        rng = random.Random(46)
        injs = [D.unknown_sku(feed, date(2026, 10, 25), card_late=8, rng=rng),
                D.scanner(feed, 4, date(2026, 10, 20), n=1, rng=rng),
                D.kopecks(feed, 4, date(2026, 10, 28), lag=2),
                D.future_date(feed, 4, date(2026, 10, 29), lag=2),
                D.missing(feed, 4, date(2026, 10, 31), late=4),
                D.negative_stock(feed, 4, n=15, lag=2, rng=rng),
                D.dup_card(feed, date(2026, 10, 15), sku="SKU-0003"),
                D.reload(feed, date(2026, 10, 21), after=2)]
    else:
        inj = D.showcase(feed, defect)
        injs = [inj] if inj else []
    return feed, injs


def run_showcase(base, defect: str, timeline: bool = False, **kw) -> ScenarioResult:
    feed, injs = showcase_feed(base, defect)
    return run_scenario(base, feed, injs, name=defect, timeline=timeline, **kw)


# --------------------------------------------------------------------------- случайные сценарии
def _one_random(args) -> dict:
    base, seed = args
    rng = random.Random(seed)
    feed = make_feed(base, seed)
    injs = D.random_defects(feed, rng)
    return asdict(run_scenario(base, feed, injs, name=f"random-{seed}"))


def random_runs(base, n: int = 200, first_seed: int = 1000, workers: int = 0) -> list[dict]:
    args = [(str(base), first_seed + i) for i in range(n)]
    if workers == 1:
        return [_one_random(a) for a in args]
    with ProcessPoolExecutor(max_workers=workers or None) as ex:
        return list(ex.map(_one_random, args))


def summarize_random(runs: list[dict]) -> dict:
    by_def: dict = {}
    for r in runs:
        for d in r["detection"]:
            s = by_def.setdefault(d["defect"], {"n": 0, "caught": 0, "caught_any": 0})
            s["n"] += 1
            s["caught"] += d["caught"]
            s["caught_any"] += d["caught_any"]
    fp: dict = {}
    for r in runs:
        for k, v in r["false_positives"].items():
            fp[k] = fp.get(k, 0) + v
    clean_files = sum(r["clean_files"] for r in runs)
    clean_rows = sum(r["clean_rows"] for r in runs)
    modes: dict = {}
    for key in ("raw", "rules01", "gate"):
        rs = [r["modes"][key] for r in runs if key in r["modes"]]
        closed = [m for m in rs if m["close_day"]]
        wrong = [m for m in closed if m["error_pct"] is None or abs(m["error_pct"]) > TOL_PCT]
        close_days = sorted(date.fromisoformat(m["close_day"]) for m in closed)
        silent = [r["modes"][key] for r in runs if key in r["modes"] and _has_silent(r)]
        loud = [r["modes"][key] for r in runs if key in r["modes"] and not _has_silent(r)]
        modes[key] = {
            "scenarios": len(rs),
            "declared_wrong_loud_only": sum(_wrong(m) for m in loud),
            "revenue_wrong_loud_only": sum(m["error_pct"] is None or abs(m["error_pct"]) > TOL_PCT for m in loud),
            "scenarios_loud_only": len(loud),
            "declared_wrong_with_silent": sum(_wrong(m) for m in silent),
            "scenarios_with_silent": len(silent),
            "closed_by_sim_end": len(closed),
            "declared_wrong": len(wrong),
            "declared_wrong_pct": round(100.0 * len(wrong) / len(rs), 1) if rs else None,
            "rewritten": sum(m["rewritten"] for m in closed),
            "all9_correct_at_close": sum(m["correct_at_close"] == len(QUESTIONS) for m in closed),
            "median_abs_error_pct": _median([abs(m["error_pct"]) for m in closed if m["error_pct"] is not None]),
            "close_day_hist": _hist(close_days),
            "close_day_median": close_days[len(close_days) // 2].isoformat() if close_days else None,
            "close_day_p90": close_days[int(len(close_days) * 0.9) - 1].isoformat() if close_days else None,
            "close_day_max": close_days[-1].isoformat() if close_days else None,
        }
    n_defects = sum(s["n"] for s in by_def.values())
    caught = sum(s["caught"] for k, s in by_def.items() if k != "truncated")
    n_loud = sum(s["n"] for k, s in by_def.items() if k != "truncated")
    return {
        "scenarios": len(runs),
        "defects": n_defects,
        "by_defect": by_def,
        "caught_loud_pct": round(100.0 * caught / n_loud, 1) if n_loud else None,
        "false_positives": fp,
        "clean_files": clean_files,
        "clean_rows": clean_rows,
        "modes": modes,
    }


def _has_silent(r: dict) -> bool:
    """Тихий дефект — обрезанный файл: даже если R08 предупредило, строки приняты и искажают итог."""
    return any(d["defect"] == "truncated" for d in r["detection"])


def _wrong(m: dict) -> bool:
    return not m["close_day"] or m["error_pct"] is None or abs(m["error_pct"]) > TOL_PCT \
        or m["correct_at_close"] != len(QUESTIONS)


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    k = len(xs) // 2
    return round(xs[k] if len(xs) % 2 else (xs[k - 1] + xs[k]) / 2, 3)


def _hist(ds: list[date]) -> dict:
    h: dict = {}
    for d in ds:
        h[d.isoformat()] = h.get(d.isoformat(), 0) + 1
    return h


def calendar_close_day() -> str:
    d = SIM_START
    while calendar_closed_through(d) < MONTH_END:
        d += timedelta(1)
    return d.isoformat()
