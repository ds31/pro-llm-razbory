from datetime import date

import pytest

from conftest import ROOT
from razbor01.golden import TRAPS, expected_value, is_correct, load_questions, scalar
from razbor01.metrics import MetricQuery, compile_query, load_catalog

QUESTIONS = load_questions(ROOT / "eval" / "questions.yaml")


def test_thirty_questions_six_per_trap():
    assert len(QUESTIONS) == 30
    for t in TRAPS:
        assert sum(q.trap == t for q in QUESTIONS) == 6, t


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q.id)
def test_check_sql_returns_number(con, q):
    assert isinstance(expected_value(con, q), float)


@pytest.mark.parametrize("q", [q for q in QUESTIONS if q.trap_sql], ids=lambda q: q.id)
def test_trap_bites(con, q):
    """Наивный запрос ошибается сильнее допуска — иначе вопрос не проверяет ловушку."""
    assert not is_correct(scalar(con, q.trap_sql), expected_value(con, q))


@pytest.mark.parametrize("q", [q for q in QUESTIONS if q.metric_query], ids=lambda q: q.id)
def test_metrics_layer_reproduces_golden(con, q):
    cat = load_catalog(ROOT / "metrics.yaml")
    mq = dict(q.metric_query)
    sql, params = compile_query(cat, MetricQuery(
        metric=mq["metric"], date_from=date.fromisoformat(mq["date_from"]), date_to=date.fromisoformat(mq["date_to"]),
        filters=mq.get("filters", {})))
    assert is_correct(float(con.execute(sql, params).fetchone()[0]), expected_value(con, q))


def test_is_correct_tolerance():
    assert is_correct(100.5, 100.0)
    assert not is_correct(100.6, 100.0)
    assert is_correct(-9.5, -9.48)
    assert not is_correct(None, 1.0)
    assert is_correct(0.0, 0.0) and not is_correct(0.1, 0.0)


def test_load_rejects_bad_file(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text("- {id: Q1, trap: none, question: x, check_sql: SELECT 1, trap_sql: SELECT 2}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="trap_sql"):
        load_questions(p)
    p.write_text("- {id: Q1, trap: none, question: x, check_sql: SELECT 1}\n"
                 "- {id: Q1, trap: none, question: y, check_sql: SELECT 1}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="повторяются"):
        load_questions(p)
