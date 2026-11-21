"""Каркас кейсов приёмки из discovery: базовый кейс на вопрос руководства, кейсы-пробы и TODO на непокрытое."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .discovery import provided_covers, required_covers

DEFAULT_TOLERANCE_PCT = 0.5


@dataclass
class Case:
    id: str
    from_q: str
    covers: list[str]
    kind: str                      # scalar — одно число; table — число на каждое значение измерения
    question: str | None
    metric_query: dict | None
    golden_sql: str | None
    signed_by: str | None
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT
    row_question: str | None = None
    hint: str | None = None
    todo: list[str] = field(default_factory=list)


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


def _norm_query(mq: dict | None) -> dict | None:
    if not mq:
        return None
    out = {k: _iso(v) for k, v in mq.items()}
    if "filters" in out:
        out["filters"] = {k: list(v) if isinstance(v, (list, tuple)) else [v] for k, v in out["filters"].items()}
    return out


def _base_query(q: dict) -> dict | None:
    period = q.get("period") or {}
    if not q.get("metric") or not period.get("from") or not period.get("to"):
        return None
    mq = {"metric": q["metric"], "date_from": _iso(period["from"]), "date_to": _iso(period["to"])}
    if q.get("dimensions"):
        mq["group_by"] = list(q["dimensions"])
    if q.get("filters"):
        mq["filters"] = q["filters"]
    if q.get("scale"):
        mq["scale"] = q["scale"]
    return _norm_query(mq)


def scaffold(d: dict) -> list[Case]:
    sources = {s.get("source"): s for s in d.get("data_map") or []}
    cases: list[Case] = []
    for q in d.get("questions") or []:
        qid = str(q.get("id"))
        golden = q.get("golden") or {}
        tol = float(q.get("tolerance_pct") or DEFAULT_TOLERANCE_PCT)
        n = 0

        def new_id() -> str:
            nonlocal n
            n += 1
            return f"{qid}-{n}"

        todo = []
        if not q.get("metric"):
            todo.append("метрика")
        if not (q.get("period") or {}).get("from"):
            todo.append("период")
        if not q.get("owner"):
            todo.append("владелец")
        if not golden.get("sql"):
            todo.append("эталон")
        if not golden.get("signed_by"):
            todo.append("подпись эталона")
        if q.get("dimensions") and not q.get("row_question"):
            todo.append("вопрос по строке")
        cases.append(Case(
            id=new_id(), from_q=qid, covers=["base"] + list(golden.get("covers") or []),
            kind="table" if q.get("dimensions") else "scalar",
            question=golden.get("question") or q.get("question"), metric_query=_base_query(q),
            golden_sql=golden.get("sql"), signed_by=golden.get("signed_by"), tolerance_pct=tol,
            row_question=q.get("row_question") if q.get("dimensions") else None, todo=todo))
        for c in q.get("checks") or []:
            todo = [label for key, label in (("question", "вопрос-проба"), ("metric_query", "metric_query"),
                                             ("golden_sql", "эталон")) if not c.get(key)]
            cases.append(Case(
                id=new_id(), from_q=qid, covers=list(c.get("covers") or []), kind="scalar",
                question=c.get("question"), metric_query=_norm_query(c.get("metric_query")),
                golden_sql=c.get("golden_sql"), signed_by=golden.get("signed_by"), tolerance_pct=tol, todo=todo))
        need = required_covers(q, sources)
        for cover in sorted(set(need) - provided_covers(q)):
            cases.append(Case(
                id=new_id(), from_q=qid, covers=[cover], kind="scalar", question=None, metric_query=None,
                golden_sql=None, signed_by=golden.get("signed_by"), tolerance_pct=tol, hint=need[cover],
                todo=["вопрос-проба", "metric_query", "эталон"]))
    return cases


HEADER = """# Кейсы приёмки — вывод `razbor06 scaffold`. Не править руками: правится discovery, каркас пересобирается.
# kind: scalar — одно число; table — число на каждое значение измерения (row_question — вопрос по строке).
# todo — чего не хватает, чтобы кейс можно было проверить.
"""


def dump_acceptance(cases: list[Case], d: dict) -> str:
    items = []
    for c in cases:
        row = {k: v for k, v in asdict(c).items() if v not in (None, [], {})}
        items.append(row)
    body = yaml.safe_dump({"project": d.get("project"), "cases": items}, allow_unicode=True, sort_keys=False,
                          width=110)
    return HEADER + body


def load_acceptance(path: Path | str) -> list[Case]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [Case(**row) for row in data.get("cases") or []]
