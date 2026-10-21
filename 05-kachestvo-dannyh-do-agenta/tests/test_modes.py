"""Три конфигурации на чистом потоке и на «всё сразу»: кто когда закрывает октябрь и что объявляет."""
import pytest

from razbor05.experiment import run_showcase
from razbor05.feed import FeedFiles, make_feed
from razbor05.modes import Truth
from razbor05.questions import QUESTIONS, answer_all


@pytest.fixture(scope="module")
def clean(base):
    return run_showcase(base, "clean")


@pytest.fixture(scope="module")
def everything(base):
    return run_showcase(base, "all")


def test_clean_close_days(clean):
    m = clean.modes
    assert (m["raw"]["close_day"], m["rules01"]["close_day"], m["gate"]["close_day"]) == \
        ("2026-11-01", "2026-11-02", "2026-11-02")


def test_clean_revenue_exact_everywhere(clean):
    for k in ("raw", "rules01", "gate"):
        assert clean.modes[k]["error_pct"] == 0, k


def test_calendar_close_misses_stock_snapshot(clean):
    """По календарю 1-го снимка остатков ещё нет: вопрос про остатки без ответа."""
    assert clean.modes["raw"]["wrong_at_close"] == ["N2"]


def test_on_nov1_gate_answers_september(clean):
    assert clean.modes["gate"]["month_on_nov1"] == "2026-09" and clean.modes["gate"]["correct_on_nov1"] == 9
    assert clean.modes["raw"]["month_on_nov1"] == "2026-10"


def test_everything_gate_right_others_wrong(everything):
    m = everything.modes
    assert m["gate"]["correct_at_close"] == 9 and abs(m["gate"]["error_pct"]) <= 0.5
    assert m["raw"]["error_pct"] > 50 and m["rules01"]["error_pct"] > 10
    assert m["raw"]["rewritten"] and m["rules01"]["rewritten"] and not m["gate"]["rewritten"]
    assert all(d["caught"] for d in everything.detection)


def test_questions_link_to_eval_01(base):
    """Q19 на сентябре = эталон Q19 пакета 01: выручка сети за сентябрь без строк-ошибок."""
    import duckdb
    with FeedFiles(make_feed(base)) as ff:
        t = Truth(base, ff)
        ans = answer_all(t.con, __import__("datetime").date(2026, 9, 30))
        con = duckdb.connect()
        con.execute(f"ATTACH '{base}' AS b (READ_ONLY)")
        q19 = con.execute("SELECT sum(amount) FROM b.raw.sales WHERE abs(qty) < 1000 "
                          "AND sale_date BETWEEN '2026-09-01' AND '2026-09-30'").fetchone()[0]
        t.close()
        con.close()
    assert len(ans) == len(QUESTIONS) == 9
    assert ans["Q19"] == pytest.approx(float(q19))
    assert ans["Q22"] in range(1, 10)
