"""Офлайн-клиент для проверки конвейера без API: сразу сдаёт эталонный ответ.

Это не агент. Им проверяют, что генератор, eval и отчёт работают на чистой копии без ключа.
"""
from __future__ import annotations

from types import SimpleNamespace

import duckdb

from .golden import Question, expected_value


class OracleClient:
    def __init__(self, con: duckdb.DuckDBPyConnection, questions: list[Question]):
        self._answers = {q.question: expected_value(con, q) for q in questions}
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, *, messages, **_):
        question = messages[0]["content"]
        block = SimpleNamespace(type="tool_use", id="oracle-1", name="final_answer",
                                input={"value": self._answers[question], "unit": "", "explanation": "офлайн-эталон"})
        return SimpleNamespace(content=[block], stop_reason="tool_use",
                               usage=SimpleNamespace(input_tokens=0, output_tokens=0))
