import json
from datetime import date

import pytest

from conftest import ROOT
from razbor03.reference import is_correct, references, scalar, trap_bites
from razbor03.scenarios import PLATFORM_ROOT, SCENARIOS, layers_sql, open_scenario
from razbor03.spec import load_suite

SUITE = load_suite(ROOT / "eval" / "questions.yaml")
RELATIVE = {"Q19", "Q20", "Q21", "Q23", "Q24"}


@pytest.fixture(scope="module")
def refs(data_dir):
    out = {}
    for name in ("base", "reload", "no-anomaly-rule"):
        con, _ = open_scenario(data_dir, name)
        try:
            out[name] = references(con, SUITE)
        finally:
            con.close()
    return out


def test_base_references_match_package_01(refs):
    """Обобщённые эталоны на данных 10.10 дают ровно числа прогона автора пакета 01."""
    ref01 = json.loads((PLATFORM_ROOT / "eval" / "reference-run.json").read_text(encoding="utf-8"))
    for a in ref01["answers"]:
        assert is_correct(refs["base"][a["qid"]], a["expected"], 1e-6), a["qid"]


def test_reload_moves_only_relative_questions(refs):
    moved = {qid for qid in refs["base"] if not is_correct(refs["reload"][qid], refs["base"][qid], 0.5)}
    assert moved == RELATIVE


def test_platform_break_does_not_touch_references(refs):
    assert refs["no-anomaly-rule"] == refs["base"]


@pytest.mark.parametrize("name", ["base", "reload"])
def test_traps_bite_in_every_data_version(data_dir, name):
    con, _ = open_scenario(data_dir, name)
    try:
        assert [q.id for q in SUITE.questions if not trap_bites(con, q)] == []
    finally:
        con.close()


def test_reload_closes_october_and_opens_november(data_dir):
    con, cat = open_scenario(data_dir, "reload")
    try:
        closed = dict(con.execute("SELECT month, is_closed FROM mart.months").fetchall())
        assert closed[date(2026, 10, 1)] is True and closed[date(2026, 11, 1)] is False
        assert con.execute("SELECT max(sale_date) FROM raw.sales").fetchone()[0] == date(2026, 11, 10)
        assert cat.closed_through == date(2026, 10, 31)
    finally:
        con.close()


def test_reload_keeps_history(data_dir):
    a, _ = open_scenario(data_dir, "base")
    b, _ = open_scenario(data_dir, "reload")
    try:
        q = "SELECT count(*), sum(amount) FROM raw.sales WHERE sale_date <= '2026-10-10'"
        assert a.execute(q).fetchone() == b.execute(q).fetchone()
    finally:
        a.close()
        b.close()


def test_stale_scenario_keeps_old_closed_through(data_dir):
    con, cat = open_scenario(data_dir, "reload-stale")
    con.close()
    assert cat.closed_through == date(2026, 9, 30) and SCENARIOS["reload-stale"].db == SCENARIOS["reload"].db


def test_no_anomaly_rule_leaks_scanner_errors_into_mart(data_dir):
    assert "abs(qty) < 1000" not in layers_sql(without_anomaly_rule=True).split("stg.sales AS")[1].split(";")[0]
    con, _ = open_scenario(data_dir, "no-anomaly-rule")
    try:
        assert scalar(con, "SELECT max(net_qty) FROM mart.sales_daily") >= 9999
    finally:
        con.close()
