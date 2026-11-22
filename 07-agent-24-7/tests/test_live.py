"""Живой режим без Docker: API на стандартной библиотеке, воркеры, kill -9 и SIGTERM посреди задачи."""
import json
import multiprocessing as mp
import os
import signal
import threading
import time
import urllib.request

import pytest

from razbor07.api import make_server
from razbor07.fakellm import Faults
from razbor07.load import check, run_load
from razbor07.queue import Queue
from razbor07.worker import Clock, Worker

QUIET = Faults(rpm_limit=10**6, p_overload=0, p_hang=0, p_drop=0, p_poison=0)
FAST = 0.0005   # минута модельного времени — 30 мс


@pytest.fixture
def api(tmp_path):
    db = tmp_path / "queue.db"
    srv = make_server(db, "127.0.0.1", 0, clock=Clock(FAST))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield db, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def test_api_dedups_and_worker_delivers_once(api):
    db, url = api
    res = run_load(url, 30, resend_share=0.5, seed=1)
    assert res["tasks"] == 30 and res["resent_with_same_key"] > 0
    assert _get(url + "/healthz") == {"ok": True}
    assert _get(url + "/stats")["counts"] == {"queued": 30}
    Worker(db, "w1", faults=QUIET, clock=Clock(FAST)).run(exit_when_idle=True)
    out = check(db)
    assert out["counts"] == {"done": 30}
    assert out["mail_sent"] == 30 and out["duplicate_mail"] == 0
    assert _get(url + "/tasks/1")["status"] == "done"


def test_crashed_lease_is_picked_up(tmp_path):
    db = tmp_path / "queue.db"
    clock = Clock(FAST)
    q = Queue(db)
    q.enqueue({"key": "k1"}, clock.now(), key="k1")
    q.claim("ghost#1", clock.now(), lease=60)   # воркер взял задачу и умер
    w = Worker(db, "w2", faults=QUIET, clock=clock)
    clock.sleep(61)
    assert w.once()
    assert check(db)["counts"] == {"done": 1}


def _slow_worker(db):
    Worker(db, "slow", faults=QUIET, clock=Clock(0.05)).run(exit_when_idle=False)


def test_sigterm_finishes_current_task_then_exits(tmp_path):
    db = tmp_path / "queue.db"
    q = Queue(db)
    q.enqueue({"key": "k1"}, Clock(0.05).now(), key="k1")
    p = mp.get_context("spawn").Process(target=_slow_worker, args=(str(db),))
    p.start()
    deadline = time.time() + 20
    while q.counts().get("leased") != 1 and time.time() < deadline:
        time.sleep(0.02)
    os.kill(p.pid, signal.SIGTERM)       # docker compose stop посреди задачи
    p.join(30)
    assert p.exitcode == 0
    assert check(db)["counts"] == {"done": 1}


def _killed_worker(db):
    Worker(db, "victim", faults=QUIET, clock=Clock(FAST), chaos_kill_p=1.0).run(exit_when_idle=True)


def test_kill9_after_send_does_not_send_twice(tmp_path):
    db = tmp_path / "queue.db"
    clock = Clock(FAST)
    q = Queue(db)
    for i in range(3):
        q.enqueue({"key": f"k{i}"}, clock.now(), key=f"k{i}")
    p = mp.get_context("spawn").Process(target=_killed_worker, args=(str(db),))
    p.start()
    p.join(30)
    assert p.exitcode == -9          # SIGKILL сразу после письма, до подтверждения
    assert check(db)["mail_sent"] == 1
    clock.sleep(61)
    Worker(db, "w2", faults=QUIET, clock=clock).run(exit_when_idle=True)
    out = check(db)
    assert out["counts"] == {"done": 3}
    assert out["mail_sent"] == 3 and out["duplicate_mail"] == 0
