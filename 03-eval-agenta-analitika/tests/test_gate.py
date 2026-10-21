import pytest

from razbor03.gate import compare, stability


def test_stability_pass_at_1_and_pass_hat_k():
    runs = [{"a": True, "b": True, "c": False}, {"a": True, "b": False, "c": False}, {"a": True, "b": True, "c": False}]
    s = stability(runs)
    assert s["k"] == 3 and s["questions"] == 3
    assert s["pass_at_1"] == pytest.approx((3 + 2 + 0) / 9, abs=1e-4)
    assert s["pass_hat_k"] == pytest.approx(1 / 3, abs=1e-4)
    assert s["flaky"] == ["b"] and s["never"] == ["c"] and s["always"] == ["a"]
    assert s["per_run"] == [2, 1, 2]


def test_stability_uses_common_questions_only():
    assert stability([{"a": True, "b": True}, {"a": True}])["questions"] == 1


def test_gate_fails_on_regression_with_exit_code():
    g = compare([{"a": True, "b": True}], [{"a": True, "b": False}])
    assert g.regressions == ["b"] and not g.ok and g.exit_code == 1


def test_gate_passes_when_nothing_breaks_and_reports_fixed():
    g = compare([{"a": True, "b": False}], [{"a": True, "b": True}])
    assert g.ok and g.exit_code == 0 and g.fixed == ["b"]


def test_flaky_before_change_does_not_block():
    old = [{"a": True}, {"a": False}, {"a": True}]
    g = compare(old, [{"a": False}])
    assert g.ok and g.flaky_before == ["a"] and g.regressions == []


def test_gate_allow_and_common_questions():
    g = compare([{"a": True, "b": True, "x": True}], [{"a": False, "b": True}], allow=1)
    assert g.questions == ["a", "b"] and g.ok
    with pytest.raises(ValueError):
        compare([{"a": True}], [{"z": True}])
