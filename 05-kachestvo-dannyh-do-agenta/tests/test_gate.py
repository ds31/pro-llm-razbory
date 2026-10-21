"""Ворота на потоке: каждое правило ловит свой дефект и молчит на чистых данных."""
from datetime import date

import duckdb
import pytest

from razbor05 import defects as D
from razbor05.experiment import run_scenario, showcase_feed
from razbor05.feed import FeedFiles, make_feed
from razbor05.gate import Gate


@pytest.fixture(scope="module")
def history(base):
    con = duckdb.connect()
    g = Gate(con, base)
    yield con, g
    con.close()


def test_history_through_rules_matches_package_01(history):
    con, g = history
    assert g.history["by_rule"] == {"R01": 40, "R07": 10}       # 40 строк qty = 9999 и 10 карточек-дублей пакета 01
    assert con.execute("SELECT count(*), count(DISTINCT sku) FROM core.products").fetchone() == (200, 200)
    assert con.execute("SELECT count(*) FROM core.sales WHERE abs(qty) >= 1000").fetchone()[0] == 0
    assert str(g.closed_through()) == "2026-09-30"


def test_history_core_equals_stg_of_01(history, base):
    con, _ = history
    con.execute(f"ATTACH '{base}' AS b (READ_ONLY)")
    try:
        raw = con.execute("SELECT sum(amount) FROM b.raw.sales WHERE abs(qty) < 1000").fetchone()[0]
    finally:
        con.execute("DETACH b")
    assert con.execute("SELECT sum(amount) FROM core.sales").fetchone()[0] == raw


@pytest.fixture(scope="module")
def clean(base):
    feed = make_feed(base)
    return run_scenario(base, feed, [], name="clean", keys=("gate",))


def test_clean_stream_no_violations_and_closes_on_snapshot_day(clean):
    assert clean.false_positives == {}
    assert clean.modes["gate"]["close_day"] == "2026-11-02"      # снимок остатков приходит 2-го
    assert clean.modes["gate"]["correct_at_close"] == 9
    assert clean.modes["gate"]["error_pct"] == 0


CASES = ["scanner", "reload", "missing", "kopecks", "negative_stock", "future_date", "unknown_sku", "dup_card"]


@pytest.mark.parametrize("defect", CASES)
def test_each_rule_catches_its_defect(base, defect):
    feed, injs = showcase_feed(base, defect)
    res = run_scenario(base, feed, injs, name=defect, keys=("gate",))
    det = res.detection[0]
    assert det["caught"], det
    assert res.false_positives == {}
    g = res.modes["gate"]
    assert g["error_pct"] is not None and abs(g["error_pct"]) <= 0.5
    assert g["correct_at_close"] == 9 and not g["rewritten"]


def test_silent_defect_passes_gate(base):
    """Граница: файл, обрезанный до правдоподобных 10 строк, правила не видят."""
    feed, injs = showcase_feed(base, "truncated")
    res = run_scenario(base, feed, injs, name="truncated", keys=("gate",))
    assert not res.detection[0]["caught_any"]
    assert res.modes["gate"]["error_pct"] < -0.5


def test_deep_truncation_warned_by_r08(base):
    feed = make_feed(base)
    inj = D.truncated(feed, 4, date(2026, 10, 10), n_days=1, cap=4)
    res = run_scenario(base, feed, [inj], keys=("gate",))
    assert res.detection[0]["rules"] == ["R08"]


def test_missing_file_holds_close_until_it_arrives(base):
    feed, injs = showcase_feed(base, "missing")
    res = run_scenario(base, feed, injs, keys=("gate",))
    assert res.modes["gate"]["close_day"] == "2026-11-05"        # файл за 31.10 пришёл 05.11


def test_resend_only_on_request(base):
    """Исправленный файл приходит, только если ворота его попросили; без ворот его никто не ждёт."""
    feed, injs = showcase_feed(base, "kopecks")
    res = run_scenario(base, feed, injs, keys=("gate",))
    assert res.gate_log["requests"] == [["2026-10-29", "sales", 4, "2026-10-28", "R04"]]


def test_reload_same_morning_is_dropped(base):
    feed = make_feed(base)
    inj = D.reload(feed, date(2026, 10, 5), after=0, stores=[3])
    res = run_scenario(base, feed, [inj], keys=("gate",))
    assert res.detection[0]["rules"] == ["R02"]
    assert res.modes["gate"]["error_pct"] == 0


def test_closed_period_rule_blocks_late_rows(base):
    """После закрытия октября строка за октябрь не проходит молча (R09)."""
    feed = make_feed(base)
    late = feed.new_load("sales", 5, date(2026, 10, 15), date(2026, 11, 8), label="late")
    feed.sales[late.load_id] = [[feed.take_sale_id(), date(2026, 10, 15), 5, "SKU-0010", 1, 100.0]]
    res = run_scenario(base, feed, [], keys=("gate",))
    assert res.false_positives.get("R09") == 1
    assert not res.modes["gate"]["rewritten"]
