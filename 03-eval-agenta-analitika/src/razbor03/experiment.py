"""Эксперимент разбора 03: три способа проверки, устойчивость на повторах, ворота.

Всё складывается в один файл-хранилище (eval/reference-run.json у автора, eval/out/experiment.json
у вас): прогоны агента, замороженные числа, вердикты судей и сводка. Платные шаги идут по плану
и пропускаются, если уже есть в хранилище, — прерванный прогон продолжается с места остановки.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from razbor01.golden import load_questions as load_questions_01

from .checkers import (agreement, check_frozen, check_judge, check_live, freeze, verdicts_from_dict,
                       verdicts_to_dict, Verdict)
from .gate import compare, stability
from .runs import Answer, Run, clip_trace, run_suite
from .scenarios import PLATFORM_ROOT, SCENARIOS, open_scenario
from .spec import Suite

MODEL = "anthropic/claude-sonnet-5.5"
JUDGES = ("anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5")
JUDGED_RUNS = ("base-A-1", "base-B-1")


@dataclass(frozen=True)
class RunSpec:
    name: str
    scenario: str
    variant: str
    tag: str | None = None      # только вопросы с этим тегом


PLAN = (
    RunSpec("base-A-1", "base", "A"), RunSpec("base-B-1", "base", "B"),
    RunSpec("no-anomaly-rule-B", "no-anomaly-rule", "B", tag="anomaly"),
    RunSpec("reload-B", "reload", "B", tag="open_month"),
    RunSpec("reload-stale-B", "reload-stale", "B", tag="open_month"),
    RunSpec("base-B-2", "base", "B"), RunSpec("base-B-3", "base", "B"),
    RunSpec("base-A-2", "base", "A"), RunSpec("base-A-3", "base", "A"),
)


# ---------- хранилище

def empty_store() -> dict:
    return {"meta": {"model": MODEL, "judges": list(JUDGES)}, "frozen": {}, "runs": {}, "judge": {}, "summary": {}}


def load_store(path: Path | str) -> dict:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_store()


def save_store(store: dict, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def store_run(store: dict, name: str) -> Run:
    return Run.from_dict(store["runs"][name])


# ---------- импорт прогона пакета 01

def import_01(results_jsonl: Path | str) -> list[Run]:
    """results.jsonl пакета 01 → два прогона base-A-1 и base-B-1 (ответы и трассы, без вердиктов)."""
    rows = [json.loads(line) for line in Path(results_jsonl).read_text(encoding="utf-8").splitlines() if line.strip()]
    runs = []
    for variant in sorted({r["variant"] for r in rows}):
        answers = [Answer(qid=r["qid"], value=r["got"], unit=r["run"]["unit"], explanation=r["run"]["explanation"],
                          trace=clip_trace(r["run"]["trace"]), cost_usd=round(r["cost_usd"], 6),
                          seconds=round(r["seconds"], 2), stop=r["stop"])
                   for r in rows if r["variant"] == variant]
        runs.append(Run(f"base-{variant}-1", {"agent": "razbor01", "variant": variant, "scenario": "base",
                                              "source": "прогон автора пакета 01"}, answers))
    return runs


# ---------- платные шаги

def execute(store: dict, suite: Suite, data_dir: Path, client, model: str = MODEL, plan=PLAN, judges=JUDGES,
            save=None, log=print, factory=None, max_usd: float | None = None) -> dict:
    """Выполнить недостающие шаги плана. save(store) — после каждого шага; max_usd — стоп по бюджету."""
    from .agent import make as default_factory
    factory = factory or default_factory
    con0, _ = open_scenario(data_dir, "base")
    try:
        store["frozen"] = {"scenario": "base", "values": freeze(suite, con0)}
    finally:
        con0.close()

    def spent() -> float:
        return total_cost(store)

    for spec in plan:
        if spec.name in store["runs"]:
            continue
        if max_usd is not None and spent() >= max_usd:
            log(f"стоп по бюджету ${max_usd}: потрачено ${spent():.2f}, {spec.name} не запущен")
            break
        con, cat = open_scenario(data_dir, spec.scenario)
        try:
            agent = factory(con=con, catalog=cat, variant=spec.variant, model=model, client=client)
            only = {q.id for q in suite.questions if q.tag == spec.tag} if spec.tag else None
            run = run_suite(agent, suite, spec.name, {"agent": "razbor01", "variant": spec.variant, "model": model,
                                                      "scenario": spec.scenario}, only=only,
                            on_answer=lambda a: log(f"{spec.name} {a.qid} {a.value} ${a.cost_usd:.4f} {a.stop}"))
        finally:
            con.close()
        store["runs"][spec.name] = run.to_dict()
        if save:
            save(store)
    for jm in judges:
        for rn in JUDGED_RUNS:
            if rn not in store["runs"] or rn in store["judge"].get(jm, {}):
                continue
            if max_usd is not None and spent() >= max_usd:
                log(f"стоп по бюджету ${max_usd}: судья {jm} на {rn} не запущен")
                continue
            vs = check_judge(store_run(store, rn), suite, client, jm,
                             on_verdict=lambda q, v: log(f"судья {jm} {rn} {q} {'верно' if v.correct else 'неверно'}"))
            store["judge"].setdefault(jm, {})[rn] = verdicts_to_dict(vs)
            if save:
                save(store)
    return store


def total_cost(store: dict) -> float:
    agent = sum(a["cost_usd"] for r in store["runs"].values() for a in r["answers"]
                if r["meta"].get("source") is None)
    judge = sum(v["cost_usd"] for per_run in store["judge"].values() for vs in per_run.values() for v in vs.values())
    return round(agent + judge, 4)


# ---------- сводка: только детерминированные пересчёты по хранилищу

def _live(store, suite, data_dir, name) -> dict[str, Verdict]:
    run = store_run(store, name)
    con, _ = open_scenario(data_dir, run.meta["scenario"])
    try:
        return check_live(run, suite, con)
    finally:
        con.close()


def _dated(run: Run, data_dir: Path) -> dict[str, Verdict]:
    """Живой SQL, но с датами внутри — как check_sql пакета 01: «последний месяц» = '2026-09-01'…'2026-09-30'."""
    from .reference import is_correct, scalar
    qs01 = {q.id: q for q in load_questions_01(PLATFORM_ROOT / "eval" / "questions.yaml")}
    con, _ = open_scenario(data_dir, run.meta["scenario"])
    try:
        out = {}
        for a in run.answers:
            exp = scalar(con, qs01[a.qid].check_sql)
            out[a.qid] = Verdict(is_correct(a.value, exp, 0.5), exp)
        return out
    finally:
        con.close()


def _ok(vs: dict[str, Verdict]) -> dict[str, bool]:
    return {q: v.correct for q, v in vs.items()}


def _gate(old, new) -> dict | None:
    try:
        g = compare(old, new)
    except ValueError:  # нет общих вопросов — сравнивать нечего
        return None
    return {"questions": g.questions, "regressions": g.regressions, "exit_code": g.exit_code}


def summarize(store: dict, suite: Suite, data_dir: Path) -> dict:
    runs = store["runs"]
    live = {name: _live(store, suite, data_dir, name) for name in runs}
    out: dict = {"runs": {}}
    for name, r in runs.items():
        n = len(r["answers"])
        out["runs"][name] = {"scenario": r["meta"]["scenario"], "variant": r["meta"]["variant"], "n": n,
                             "correct": sum(v.correct for v in live[name].values()),
                             "cost_usd": round(sum(a["cost_usd"] for a in r["answers"]), 4),
                             "seconds_per_q": round(sum(a["seconds"] for a in r["answers"]) / n, 1)}

    # 1. Три способа проверки на ответах прогона автора
    judged = [n for n in JUDGED_RUNS if n in runs]
    if judged:
        truth = {f"{n}:{q}": v for n in judged for q, v in live[n].items()}
        checks = {"live": {"answers": len(truth), "errors": sum(not v.correct for v in truth.values()),
                           "missed": [], "rejected": []}}
        for jm, per_run in store["judge"].items():
            if all(n in per_run for n in judged):
                other = {f"{n}:{q}": v for n in judged for q, v in verdicts_from_dict(per_run[n]).items()}
                checks[jm] = agreement(truth, other)
                checks[jm]["cost_usd"] = round(sum(v.cost_usd for v in other.values()), 4)
        out["checkers"] = checks

    # 2. Дозагрузка: живой эталон против замороженного и против SQL с датами внутри
    frozen = store.get("frozen", {}).get("values")
    drift = {}
    for name in ("reload-B", "reload-stale-B"):
        if name in runs and frozen:
            run = store_run(store, name)
            drift[name] = {
                "live_correct": sum(v.correct for v in live[name].values()), "answers": len(run.answers),
                "frozen": agreement(live[name], check_frozen(run, suite, frozen)),
                "dated_sql": agreement(live[name], _dated(run, data_dir)),
            }
    if drift:
        out["drift"] = drift

    # 3. Устойчивость на повторах
    stab = {}
    for v in ("A", "B"):
        names = sorted(n for n in runs if n.startswith(f"base-{v}-"))
        if names:
            stab[v] = {"runs": names, **stability([_ok(live[n]) for n in names])}
    out["stability"] = stab

    # 4. Ворота
    gate = {}
    base_b = sorted(n for n in runs if n.startswith("base-B-"))
    for key, new in (("no-anomaly-rule", "no-anomaly-rule-B"), ("reload-stale", "reload-stale-B")):
        if base_b and new in runs:
            g = _gate([_ok(live[n]) for n in base_b], [_ok(live[new])])
            if g:
                gate[key] = {"old": base_b, "new": new, **g}
    if len(base_b) >= 2:
        g = _gate([_ok(live[base_b[0]])], [_ok(live[n]) for n in base_b[1:]])
        if g:
            gate["no-change"] = {"old": base_b[:1], "new": base_b[1:], **g}
    out["gate"] = gate
    out["cost_usd_total"] = total_cost(store)
    out["live"] = {n: {q: {"correct": v.correct, "expected": v.expected} for q, v in vs.items()} for n, vs in live.items()}
    return out
