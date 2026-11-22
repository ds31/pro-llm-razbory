"""Четыре стратегии загрузки на одной и той же неделе жизни источника."""
import json

import pytest

from razbor08.experiment import STRATEGIES, run_volume

from .conftest import START, TINY


@pytest.fixture(scope="module")
def week(tmp_path_factory):
    out = tmp_path_factory.mktemp("week")
    return run_volume(TINY, nights=7, sim_start=START, seed=8, work_dir=out)


def test_all_strategies_reported(week):
    assert set(week["strategies"]) == set(STRATEGIES)
    for s in week["strategies"].values():
        assert len(s["series"]) == 7
    assert week["initial"]["rows"] > 0


def test_full_reload_never_diverges(week):
    assert all(n["sales_days_bad"] == 0 and n["stock_cells_bad"] == 0 and n["month_end_cells_bad"] == 0
               for n in week["strategies"]["full"]["series"])


def test_safe_converges_after_weekly_reconciliation(week):
    series = week["strategies"]["safe"]["series"]
    assert any(n["sales_days_bad"] > 0 for n in series)          # прямое удаление живёт до сверки
    assert series[-1]["reconciled_pairs"] > 0                     # воскресенье — сверка
    last = series[-1]
    assert last["sales_days_bad"] == 0 and last["stock_cells_bad"] == 0 and last["month_end_cells_bad"] == 0


def test_naive_increments_keep_errors(week):
    assert week["strategies"]["watermark"]["final"]["sales_days_bad"] > 0   # поздние записи потеряны
    assert week["strategies"]["doc_date"]["final"]["sales_days_bad"] > 0    # правки старше окна не видны


def test_increments_read_less_than_full(week):
    full = week["strategies"]["full"]["per_night"]["rows_avg"]
    for k in ("doc_date", "watermark", "safe"):
        assert week["strategies"][k]["per_night"]["rows_avg"] < full / 3


def test_month_level_tolerance(week):
    assert week["strategies"]["full"]["final"]["store_months_bad"] == 0
    assert week["strategies"]["safe"]["final"]["store_months_bad"] == 0
    assert week["strategies"]["full"]["final"]["last_full_month_err_pct"] == 0


def test_json_serializable(week):
    json.dumps(week, ensure_ascii=False)
