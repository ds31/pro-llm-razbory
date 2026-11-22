"""Эксперимент: одна ночь во всех конфигурациях, сбои по одному, N ночей с разными seed, пример трассы."""
from __future__ import annotations

import os
import statistics
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime

from .agent import CONFIGS, PROD
from .fakellm import Faults
from .sim import Night, simulate

MAIN_SEED = 48            # неделя разбора — W48
NIGHTS_FIRST_SEED = 1000
KEYS = ("naive", "queue", "prod")

_D, _F = Night(), Faults()
QUIET = replace(_D, crash_every=0.0, p_lost_response=0.0,
                faults=Faults(rpm_limit=10**6, p_overload=0, p_hang=0, p_drop=0, p_poison=0))


def _with(**faults) -> Night:
    return replace(QUIET, faults=replace(QUIET.faults, **faults))


PROFILES: dict[str, tuple[str, Night]] = {
    "clean": ("Без сбоев", QUIET),
    "rate_limit": (f"Лимит {_F.rpm_limit} запросов в минуту, утренний пик", _with(rpm_limit=_F.rpm_limit)),
    "overload": ("Перегрузка провайдера (529), 1 % вызовов", _with(p_overload=_F.p_overload)),
    "hang": ("Вызов завис и не отвечает, 0,5 %", _with(p_hang=_F.p_hang)),
    "drop": ("Обрыв соединения посреди ответа, 1 %", _with(p_drop=_F.p_drop)),
    "kill9": ("kill -9 процесса в среднем раз в 30 минут", replace(QUIET, crash_every=_D.crash_every)),
    "lost_response": ("Ответ API клиенту потерялся, 1 %", replace(QUIET, p_lost_response=_D.p_lost_response)),
    "poison": ("Битая задача: 400 на каждом вызове, 0,5 %", _with(p_poison=_F.p_poison)),
    "all": ("Всё вместе — ночь по умолчанию", _D),
}


def _one(args):
    cfg_name, night, seed = args
    return simulate(CONFIGS[cfg_name], night, seed).metrics


def _pool(jobs, workers: int):
    if workers == 1 or len(jobs) == 1:
        return [_one(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as ex:
        return list(ex.map(_one, jobs, chunksize=4))


def run_profiles(seed: int = MAIN_SEED, workers: int = 0, profiles=None) -> dict:
    names = list(profiles or PROFILES)
    jobs = [(k, PROFILES[p][1], seed) for p in names for k in KEYS]
    res = iter(_pool(jobs, workers))
    return {p: {"title": PROFILES[p][0], "configs": {k: next(res) for k in KEYS}} for p in names}


def _stats(vals: list[float]) -> dict:
    return {"min": min(vals), "median": statistics.median(vals), "max": max(vals), "sum": sum(vals)}


def run_nights(n: int, first_seed: int = NIGHTS_FIRST_SEED, workers: int = 0) -> dict:
    jobs = [(k, _D, s) for s in range(first_seed, first_seed + n) for k in KEYS]
    res = _pool(jobs, workers)
    by = {k: [res[i * len(KEYS) + j] for i in range(n)] for j, k in enumerate(KEYS)}
    summary = {}
    for k, ms in by.items():
        summary[k] = {
            "lost": _stats([m["lost"] for m in ms]),
            "nights_with_lost": sum(m["lost"] > 0 for m in ms),
            "dup_tasks": _stats([m["dup_tasks"] for m in ms]),
            "nights_with_dup": sum(m["dup_tasks"] > 0 for m in ms),
            "dead": _stats([m["dead"] for m in ms]),
            "nights_with_exhausted": sum(m["dead_exhausted"] > 0 for m in ms),
            "dead_exhausted": _stats([m["dead_exhausted"] for m in ms]),
            "p50": _stats([m["p50"] for m in ms]),
            "p95": _stats([m["p95"] for m in ms]),
            "trace_incomplete": _stats([m["tasks"] - m["trace_complete"] for m in ms]),
            "calls_per_delivered": _stats([m["calls_per_delivered"] for m in ms]),
            "crashes": _stats([m["crashes"] for m in ms]),
        }
    return {"n": n, "first_seed": first_seed, "tasks_per_night": _D.tasks, "summary": summary}


def trace_example(seed: int = MAIN_SEED) -> dict:
    """Задача, которую в проде убили kill -9 и повторили после письма: та же задача во всех конфигурациях."""
    prod = simulate(PROD, _D, seed)
    by_task: dict[str, list[dict]] = {}
    for e in prod.events:
        if "task" in e:
            by_task.setdefault(e["task"], []).append(e)

    def score(evs):
        names = {e["event"] for e in evs}
        return ("lease_expired" in names) * 2 + ("send_deduped" in names) * 4 + ("retry_scheduled" in names)

    key = max(by_task, key=lambda k: (score(by_task[k]), -int(k.rsplit("-", 1)[1])))
    out = {"task": key, "seed": seed, "configs": {}}
    for name in KEYS:
        res = prod if name == "prod" else simulate(CONFIGS[name], _D, seed)
        out["configs"][name] = [e for e in res.events if e.get("task") == key]
    return out


def run_all(nights: int = 100, workers: int = 0, seed: int = MAIN_SEED) -> dict:
    faults = run_profiles(seed, workers)
    return {
        "meta": {
            "run_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "llm": "нет — фейковая модель с профилем сбоев (src/razbor07/fakellm.py)",
            "time": "виртуальные секунды: симулятор двигает часы сам",
            "main_seed": seed,
            "night": asdict(_D),
            "configs": {k: asdict(CONFIGS[k]) for k in KEYS},
        },
        "main": faults["all"]["configs"],
        "faults": faults,
        "nights": run_nights(nights, workers=workers),
        "trace_example": trace_example(seed),
    }
