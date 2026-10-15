"""Эталоны eval: вопросы из eval/questions.yaml и сравнение ответа с допуском."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import yaml

TRAPS = ("none", "dup_join", "anomaly", "open_month", "definition")
TOLERANCE_PCT = 0.5


@dataclass(frozen=True)
class Question:
    id: str
    trap: str
    question: str
    check_sql: str
    trap_sql: str | None = None
    metric_query: dict | None = None


def load_questions(path: Path | str) -> list[Question]:
    items = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    qs = [Question(**item) for item in items]
    ids = [q.id for q in qs]
    if len(ids) != len(set(ids)):
        raise ValueError("повторяются id вопросов")
    for q in qs:
        if q.trap not in TRAPS:
            raise ValueError(f"{q.id}: неизвестная ловушка {q.trap}")
        if (q.trap == "none") != (q.trap_sql is None):
            raise ValueError(f"{q.id}: trap_sql нужен всем вопросам, кроме ловушки none")
    return qs


def scalar(con: duckdb.DuckDBPyConnection, sql: str) -> float:
    row = con.execute(sql).fetchone()
    if row is None or row[0] is None:
        raise ValueError(f"запрос вернул пусто: {sql}")
    return float(row[0])


def expected_value(con: duckdb.DuckDBPyConnection, q: Question) -> float:
    return scalar(con, q.check_sql)


def is_correct(got: float | None, expected: float, tol_pct: float = TOLERANCE_PCT) -> bool:
    if got is None:
        return False
    if expected == 0:
        return abs(got) < 1e-9
    return abs(got - expected) <= abs(expected) * tol_pct / 100
