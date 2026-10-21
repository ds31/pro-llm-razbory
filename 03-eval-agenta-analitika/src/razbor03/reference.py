"""Живой эталон: число считается запросом check_sql по текущим данным при каждой проверке."""
from __future__ import annotations

import duckdb

from .spec import Question, Suite


def scalar(con: duckdb.DuckDBPyConnection, sql: str) -> float:
    row = con.execute(sql).fetchone()
    if row is None or row[0] is None:
        raise ValueError(f"запрос вернул пусто: {sql}")
    return float(row[0])


def expected(con: duckdb.DuckDBPyConnection, q: Question) -> float:
    return scalar(con, q.check_sql)


def is_correct(got: float | None, exp: float, tol_pct: float = 0.5) -> bool:
    if got is None:
        return False
    if exp == 0:
        return abs(got) < 1e-9
    return abs(got - exp) <= abs(exp) * tol_pct / 100 + 1e-9


def trap_bites(con: duckdb.DuckDBPyConnection, q: Question) -> bool:
    """Запрос-ловушка даёт другое число — иначе вопрос не отличает агента, который в неё попал."""
    if not q.trap_sql:
        return True
    return not is_correct(scalar(con, q.trap_sql), expected(con, q), q.tolerance_pct)


def references(con: duckdb.DuckDBPyConnection, suite: Suite) -> dict[str, float]:
    return {q.id: expected(con, q) for q in suite.questions}
