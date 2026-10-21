"""Формат набора eval (eval/questions.yaml): вопросы, теги-ловушки, живые эталоны, допуск.

Каркас переносится на любого агента-аналитика: вопрос руководителя + SELECT, который считает
правильное число по сырым данным с правилами компании. Числа в файле не хранятся.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CONTROL_TAG = "none"
FIELDS = {"id", "tag", "question", "check_sql", "trap_sql", "tolerance_pct"}


class SpecError(ValueError):
    """Набор вопросов нарушает формат."""


@dataclass(frozen=True)
class Question:
    id: str
    tag: str
    question: str
    check_sql: str
    trap_sql: str | None = None
    tolerance_pct: float = 0.5


@dataclass(frozen=True)
class Suite:
    tags: dict[str, str]
    questions: tuple[Question, ...]

    def get(self, qid: str) -> Question:
        for q in self.questions:
            if q.id == qid:
                return q
        raise KeyError(qid)


def _is_select(sql: str) -> bool:
    head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    return head in {"SELECT", "WITH"}


def load_suite(path: Path | str) -> Suite:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    tags = dict(raw.get("tags") or {})
    default_tol = float(raw.get("tolerance_pct", 0.5))
    qs, seen = [], set()
    for item in raw["questions"]:
        extra = set(item) - FIELDS
        if extra:
            raise SpecError(f"{item.get('id')}: неизвестное поле {sorted(extra)}; эталон — только check_sql")
        q = Question(id=str(item["id"]), tag=item["tag"], question=item["question"], check_sql=item["check_sql"],
                     trap_sql=item.get("trap_sql"), tolerance_pct=float(item.get("tolerance_pct", default_tol)))
        if q.id in seen:
            raise SpecError(f"повторяется id {q.id}")
        seen.add(q.id)
        if q.tag not in tags:
            raise SpecError(f"{q.id}: неизвестный тег {q.tag}; доступны: {', '.join(tags)}")
        for name, sql in (("check_sql", q.check_sql), ("trap_sql", q.trap_sql)):
            if sql is not None and not _is_select(sql):
                raise SpecError(f"{q.id}: {name} должен быть SELECT или WITH … SELECT")
        if q.tag == CONTROL_TAG and q.trap_sql:
            raise SpecError(f"{q.id}: у контрольного вопроса (tag: {CONTROL_TAG}) нет trap_sql")
        if q.tag != CONTROL_TAG and not q.trap_sql:
            raise SpecError(f"{q.id}: вопрос с ловушкой {q.tag} без trap_sql — нечем проверить, что ловушка кусает")
        if q.tolerance_pct < 0:
            raise SpecError(f"{q.id}: отрицательный допуск")
        qs.append(q)
    return Suite(tags=tags, questions=tuple(qs))
