import pytest

from conftest import ROOT
from razbor03.spec import SpecError, load_suite

SUITE = load_suite(ROOT / "eval" / "questions.yaml")


def _write(tmp_path, body: str):
    p = tmp_path / "q.yaml"
    p.write_text("version: 1\ntolerance_pct: 0.5\ntags: {none: контроль, dup: дубли}\n" + body, encoding="utf-8")
    return p


def test_suite_has_thirty_questions_six_per_tag():
    assert len(SUITE.questions) == 30
    for tag in SUITE.tags:
        assert sum(q.tag == tag for q in SUITE.questions) == 6, tag


def test_default_and_own_tolerance():
    by_id = {q.id: q for q in SUITE.questions}
    assert by_id["Q01"].tolerance_pct == 0.5
    assert by_id["Q13"].tolerance_pct == 0      # номер магазина — точное совпадение


def test_question_needs_trap_sql_unless_control(tmp_path):
    p = _write(tmp_path, "questions:\n- {id: X1, tag: dup, question: q, check_sql: SELECT 1}\n")
    with pytest.raises(SpecError, match="trap_sql"):
        load_suite(p)


def test_control_question_without_trap(tmp_path):
    p = _write(tmp_path, "questions:\n- {id: X1, tag: none, question: q, check_sql: SELECT 1, trap_sql: SELECT 2}\n")
    with pytest.raises(SpecError, match="контрольн"):
        load_suite(p)


def test_unknown_tag_and_duplicate_id(tmp_path):
    with pytest.raises(SpecError, match="тег"):
        load_suite(_write(tmp_path, "questions:\n- {id: X1, tag: zzz, question: q, check_sql: SELECT 1}\n"))
    with pytest.raises(SpecError, match="повтор"):
        load_suite(_write(tmp_path, "questions:\n- {id: X1, tag: none, question: q, check_sql: SELECT 1}\n"
                                    "- {id: X1, tag: none, question: q2, check_sql: SELECT 1}\n"))


def test_check_sql_must_be_select(tmp_path):
    with pytest.raises(SpecError, match="SELECT"):
        load_suite(_write(tmp_path, "questions:\n- {id: X1, tag: none, question: q, check_sql: DELETE FROM t}\n"))


def test_unknown_field_rejected(tmp_path):
    with pytest.raises(SpecError, match="поле"):
        load_suite(_write(tmp_path, "questions:\n- {id: X1, tag: none, question: q, check_sql: SELECT 1, expected: 5}\n"))


def test_no_date_literals_in_relative_questions():
    """«Последний месяц» считается по данным: дата-литерал в эталоне устареет при дозагрузке."""
    for q in SUITE.questions:
        if "последн" in q.question:
            assert "'2026-" not in q.check_sql, q.id
