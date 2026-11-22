import math

from razbor07.fakellm import Faults, FakeModel

QUIET = Faults(rpm_limit=10_000, p_overload=0, p_hang=0, p_drop=0, p_poison=0)


def test_same_seed_same_outcome():
    a = FakeModel(Faults(), seed=7).call(0.0, "store-01:q1", "1.plan.0")
    b = FakeModel(Faults(), seed=7).call(0.0, "store-01:q1", "1.plan.0")
    assert a == b


def test_quiet_model_always_ok_with_tokens_and_latency():
    m = FakeModel(QUIET, seed=1)
    outs = [m.call(i * 10.0, f"t{i}", "1.plan.0") for i in range(200)]
    assert {o.kind for o in outs} == {"ok"}
    assert all(o.tokens_in > 0 and o.tokens_out > 0 for o in outs)
    lat = sorted(o.duration for o in outs)
    assert 2.0 < lat[100] < 4.5  # медиана около 3 с


def test_rate_limit_returns_429_with_retry_after():
    m = FakeModel(Faults(rpm_limit=3, p_overload=0, p_hang=0, p_drop=0, p_poison=0), seed=1)
    kinds = [m.call(t, f"t{t}", "1.plan.0") for t in (0.0, 1.0, 2.0, 3.0)]
    assert [k.kind for k in kinds] == ["ok", "ok", "ok", "rate_limited"]
    assert math.isclose(kinds[3].retry_after, 57.0)
    # окно сдвинулось — снова принимает
    assert m.call(60.5, "t5", "1.plan.0").kind == "ok"


def test_rejected_calls_do_not_fill_the_window():
    m = FakeModel(Faults(rpm_limit=1, p_overload=0, p_hang=0, p_drop=0, p_poison=0), seed=1)
    assert m.call(0.0, "a", "x").kind == "ok"
    for t in range(1, 50):
        assert m.call(float(t), "b", f"x{t}").kind == "rate_limited"
    assert m.call(60.1, "b", "y").kind == "ok"


def test_fault_shares_match_profile():
    f = Faults(rpm_limit=10**9, p_overload=0.05, p_hang=0.05, p_drop=0.05, p_poison=0)
    m = FakeModel(f, seed=3)
    outs = [m.call(0.0, f"t{i}", "1.plan.0").kind for i in range(20_000)]
    for kind in ("overloaded", "hang", "drop"):
        share = outs.count(kind) / len(outs)
        assert 0.04 < share < 0.06, (kind, share)


def test_hang_never_returns_and_drop_is_mid_answer():
    f = Faults(rpm_limit=10**9, p_overload=0, p_hang=0.5, p_drop=0.5, p_poison=0)
    m = FakeModel(f, seed=3)
    outs = [m.call(0.0, f"t{i}", "1.plan.0") for i in range(200)]
    assert all(math.isinf(o.duration) for o in outs if o.kind == "hang")
    drops = [o for o in outs if o.kind == "drop"]
    assert drops and all(0 < o.duration < 30 for o in drops)


def test_poison_task_fails_every_call_and_is_not_retryable():
    f = Faults(p_poison=1.0)
    m = FakeModel(f, seed=1)
    o = m.call(0.0, "bad", "1.plan.0")
    assert o.kind == "bad_request" and not o.retryable
    assert m.call(100.0, "bad", "2.plan.0").kind == "bad_request"


def test_retryable_kinds():
    m = FakeModel(Faults(rpm_limit=0, p_poison=0), seed=1)
    assert m.call(0.0, "a", "x").retryable  # 429
