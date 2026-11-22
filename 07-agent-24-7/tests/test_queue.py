import random

import pytest

from razbor07.queue import Queue, backoff


@pytest.fixture
def q():
    return Queue(":memory:")


def test_enqueue_dedups_by_key(q):
    a, new_a = q.enqueue({"q": "выручка"}, now=0, key="store-01:q1")
    b, new_b = q.enqueue({"q": "выручка"}, now=1, key="store-01:q1")
    assert new_a and not new_b and a == b
    c, new_c = q.enqueue({"q": "выручка"}, now=2, key=None)
    assert new_c and c != a
    assert q.counts() == {"queued": 2}


def test_claim_leases_and_ack(q):
    tid, _ = q.enqueue({}, now=0, key="k")
    t = q.claim("w1#1", now=1, lease=60)
    assert t.id == tid and t.attempt == 1 and t.key == "k" and t.reclaimed_from is None
    assert q.claim("w2#1", now=2, lease=60) is None  # занята
    assert q.ack(tid, "w1#1", now=5)
    assert q.counts() == {"done": 1}


def test_not_before_available_at(q):
    tid, _ = q.enqueue({}, now=0, key="k")
    t = q.claim("w1#1", now=0, lease=60)
    assert q.fail(t.id, "w1#1", now=1, error="429", retryable=True, delay=10, max_attempts=5) == "retry"
    assert q.claim("w1#2", now=5, lease=60) is None
    t2 = q.claim("w1#2", now=11, lease=60)
    assert t2.id == tid and t2.attempt == 2


def test_expired_lease_is_reclaimed_and_reports_previous_owner(q):
    tid, _ = q.enqueue({}, now=0, key="k")
    q.claim("w1#1", now=0, lease=60)
    assert q.claim("w2#1", now=59, lease=60) is None
    t = q.claim("w2#1", now=61, lease=60)
    assert t.id == tid and t.attempt == 2 and t.reclaimed_from == "w1#1"
    # старый владелец не может подтвердить чужую аренду
    assert not q.ack(tid, "w1#1", now=62)
    assert q.ack(tid, "w2#1", now=63)


def test_heartbeat_extends_lease(q):
    q.enqueue({}, now=0, key="k")
    t = q.claim("w1#1", now=0, lease=60)
    assert q.heartbeat(t.id, "w1#1", now=50, lease=60)
    assert q.claim("w2#1", now=100, lease=60) is None
    assert q.claim("w2#1", now=111, lease=60) is not None


def test_dead_letter_after_max_attempts_and_non_retryable(q):
    q.enqueue({}, now=0, key="a")
    for i in range(3):
        t = q.claim(f"w#{i}", now=100 * i, lease=60)
        res = q.fail(t.id, f"w#{i}", now=100 * i + 1, error="timeout", retryable=True, delay=1, max_attempts=3)
    assert res == "dead"
    q.enqueue({}, now=400, key="b")
    t = q.claim("w#9", now=400, lease=60)
    assert q.fail(t.id, "w#9", now=401, error="400 bad_request", retryable=False, delay=0, max_attempts=3) == "dead"
    dead = q.dead_letters()
    assert [d["key"] for d in dead] == ["a", "b"]
    assert dead[1]["last_error"] == "400 bad_request"


def test_reclaim_after_max_attempts_goes_dead(q):
    tid, _ = q.enqueue({}, now=0, key="k")
    q.claim("w1#1", now=0, lease=10, max_attempts=1)
    assert q.claim("w2#1", now=20, lease=10, max_attempts=1) is None
    assert q.counts() == {"dead": 1}
    assert q.reclaimed_dead == [(tid, "w1#1")]


def test_requeue_dead(q):
    tid, _ = q.enqueue({}, now=0, key="k")
    t = q.claim("w", now=0, lease=10)
    q.fail(t.id, "w", now=1, error="x", retryable=False, delay=0, max_attempts=3)
    assert q.requeue_dead(tid, now=5)
    assert q.claim("w2", now=5, lease=10).id == tid


def test_backoff_full_jitter_and_cap():
    r = random.Random(1)
    vals = [backoff(a, r, base=2, cap=300) for a in range(1, 12) for _ in range(50)]
    assert all(0 <= v <= 300 for v in vals)
    assert max(backoff(1, random.Random(i), base=2, cap=300) for i in range(100)) <= 4
    assert backoff(3, r, base=2, cap=300, retry_after=42.0) >= 42.0


def test_file_queue_shared_between_connections(tmp_path):
    p = tmp_path / "queue.db"
    api, worker = Queue(p), Queue(p)
    api.enqueue({"q": 1}, now=0, key="k")
    assert worker.claim("w", now=1, lease=60).payload == {"q": 1}
