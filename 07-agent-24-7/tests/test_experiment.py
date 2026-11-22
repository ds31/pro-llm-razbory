"""Критерий «прошёл» пакета 07 (eval/README.md) на ночи по умолчанию и на нескольких seed."""
import pytest

from razbor07.experiment import PROFILES, run_nights, run_profiles, trace_example


@pytest.fixture(scope="module")
def faults():
    return run_profiles(workers=1)


def test_profiles_cover_every_fault(faults):
    assert set(faults) == set(PROFILES)
    for p in faults.values():
        assert set(p["configs"]) == {"naive", "queue", "prod"}


def test_prod_never_loses_or_duplicates(faults):
    for name, p in faults.items():
        m = p["configs"]["prod"]
        assert m["lost"] == 0, name
        assert m["dup_tasks"] == 0, name
        assert m["trace_complete"] == m["tasks"], name
        assert m["delivered"] + m["dead"] == m["tasks"], name


def test_clean_night_is_equal_for_all(faults):
    for m in faults["clean"]["configs"].values():
        assert m["delivered"] == 1000 and m["dup_tasks"] == 0 and m["lost"] == 0


def test_dead_letter_only_for_poison_in_prod(faults):
    for name, p in faults.items():
        if name not in ("poison", "all"):
            assert p["configs"]["prod"]["dead"] == 0, name
    assert faults["poison"]["configs"]["prod"]["dead"] == faults["poison"]["configs"]["naive"]["lost"]


def test_naive_suffers_under_default_night(faults):
    m = faults["all"]["configs"]
    assert m["naive"]["lost"] > 0 and m["naive"]["dup_tasks"] > 0
    assert m["queue"]["lost"] == 0 and m["queue"]["dup_tasks"] > 0
    assert m["naive"]["trace_complete"] < 1000


def test_nights_summary_shape():
    s = run_nights(2, workers=1)
    assert s["n"] == 2
    assert s["summary"]["prod"]["nights_with_lost"] == 0
    assert s["summary"]["prod"]["nights_with_dup"] == 0
    assert s["summary"]["prod"]["dead_exhausted"]["max"] == 0


def test_trace_example_survives_kill9_without_second_letter():
    ex = trace_example()
    names = [e["event"] for e in ex["configs"]["prod"]]
    assert "lease_expired" in names and names[-1] == "done"
    assert names.count("send") == 1
