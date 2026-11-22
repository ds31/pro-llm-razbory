from dataclasses import replace

import pytest

from razbor07.agent import NAIVE, PROD, QUEUE
from razbor07.fakellm import Faults
from razbor07.sim import Night, simulate, workload

QUIET = Faults(rpm_limit=10**6, p_overload=0, p_hang=0, p_drop=0, p_poison=0)
CALM = Night(tasks=200, hours=1, crash_every=0, p_lost_response=0, faults=QUIET)


def test_workload_is_deterministic_with_morning_peak():
    a, b = workload(Night(), 7), workload(Night(), 7)
    assert a == b and len(a) == 1000
    assert len({t.key for t in a}) == 1000
    n = Night()
    in_peak = sum(n.peak_at <= t.arrival <= n.peak_at + n.peak_len for t in a)
    assert in_peak >= 300
    assert workload(Night(), 8) != a


@pytest.mark.parametrize("cfg", [NAIVE, QUEUE, PROD], ids=lambda c: c.name)
def test_calm_night_every_task_exactly_once(cfg):
    m = simulate(cfg, CALM, seed=1).metrics
    assert m["delivered"] == 200 and m["lost"] == 0 and m["dup_tasks"] == 0 and m["dead"] == 0
    assert m["trace_complete"] == 200
    assert m["calls_billed"] == 600
    assert 5 < m["p50"] < 20


def _metrics(cfg, night, seed):
    return simulate(cfg, night, seed).metrics


@pytest.mark.parametrize("cfg", [NAIVE, QUEUE, PROD], ids=lambda c: c.name)
def test_same_seed_same_metrics_across_processes(cfg):
    """Порядок событий не должен зависеть от адресов объектов в памяти: сверяем с другим процессом."""
    import multiprocessing as mp
    n = replace(Night(tasks=300, hours=1, peak_share=0.6), crash_every=300)
    with mp.get_context("spawn").Pool(1) as pool:
        other = pool.apply(_metrics, (cfg, n, 3))
    assert simulate(cfg, n, seed=3).metrics == other


def test_kill9_naive_loses_traces_prod_recovers_without_duplicates():
    n = replace(CALM, crash_every=300)
    naive, queue, prod = (simulate(c, n, seed=2).metrics for c in (NAIVE, QUEUE, PROD))
    assert naive["crashes"] > 0 and prod["crashes"] > 0
    assert naive["trace_complete"] < 200
    assert prod["lost"] == 0 and prod["dup_tasks"] == 0 and prod["trace_complete"] == 200
    assert queue["lost"] == 0 and queue["dup_tasks"] > 0


def test_poison_goes_to_dead_letter_not_lost():
    n = replace(CALM, faults=replace(QUIET, p_poison=0.05))
    prod, naive = simulate(PROD, n, seed=4).metrics, simulate(NAIVE, n, seed=4).metrics
    assert prod["dead"] > 0 and prod["lost"] == 0
    assert prod["dead"] + prod["delivered"] == 200
    assert naive["lost"] == prod["dead"] and naive["dead"] == 0


def test_lost_response_duplicates_without_key_only():
    n = replace(CALM, p_lost_response=0.1)
    q, p = simulate(QUEUE, n, seed=5).metrics, simulate(PROD, n, seed=5).metrics
    assert q["dup_tasks"] > 0 and p["dup_tasks"] == 0 and p["dedup_enqueue"] > 0


def test_failure_after_send_duplicates_without_key_only():
    n = replace(CALM, faults=replace(QUIET, p_drop=0.3))
    q, p = simulate(QUEUE, n, seed=6).metrics, simulate(PROD, n, seed=6).metrics
    assert q["dup_tasks"] > 0 and p["dup_tasks"] == 0 and p["dedup_send"] > 0
    assert p["lost"] == 0


def test_rate_limit_peak_hurts_naive_more():
    n = replace(Night(tasks=300, hours=1, peak_share=0.8), crash_every=0, p_lost_response=0,
                faults=replace(QUIET, rpm_limit=50))
    naive, prod = simulate(NAIVE, n, seed=7).metrics, simulate(PROD, n, seed=7).metrics
    assert naive["rejected_429"] > prod["rejected_429"]
    assert naive["lost"] > 0 and prod["lost"] == 0


def test_trace_of_task_has_cost_and_terminal_events():
    res = simulate(PROD, CALM, seed=1)
    key = res.tasks[0].key
    ev = [e for e in res.events if e.get("task") == key]
    names = [e["event"] for e in ev]
    assert names[0] == "received" and "claimed" in names and names[-1] == "done"
    calls = [e for e in ev if e["event"] == "call"]
    assert len(calls) == 3 and all(e["cost_usd"] > 0 and e["ms"] > 0 for e in calls)
