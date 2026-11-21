"""Ворота приёмки G1–G5: кейсы полные, эталоны считаются, слой сходится с эталоном, агент отвечает верно,
цена и время в пределах спеки. Вердикт: «принят», «не принят» или «ждёт прогона»."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import duckdb
from razbor01.golden import is_correct
from razbor01.metrics import Catalog, MetricQuery, compile_query

from .answers import Answer, Key
from .discovery import metric_parts
from .scaffold import Case

PASS, FAIL, WAIT, NA = "пройдены", "не пройдены", "ждёт прогона", "не применимо"
GATES = {
    "G1": "кейсы полные: у каждого есть вопрос, запрос к слою и эталон",
    "G2": "эталоны считаются: каждый запрос владельца даёт число",
    "G3": "слой метрик даёт эталонное число на каждом кейсе",
    "G4": "агент отвечает в допуске на каждом кейсе",
    "G5": "средняя цена и время ответа в пределах спеки",
}


@dataclass
class Gate:
    status: str
    detail: str = ""


@dataclass
class Waiting:
    case_id: str
    question: str
    golden_sql: str
    metric_query: dict | None


@dataclass
class CaseResult:
    id: str
    from_q: str
    covers: list[str]
    kind: str
    question: str | None
    expected: float | dict | None = None
    layer: float | dict | None = None
    layer_ok: bool | None = None
    answer: float | None = None          # скаляр: ответ агента
    rows_answered: int = 0
    rows_total: int = 0
    rows_correct: int = 0
    status: str = ""                     # верно · ошибка · ждёт прогона · нет эталона · не готов
    error: str = ""


@dataclass
class Verdict:
    variant: str
    verdict: str
    gates: dict[str, Gate]
    cases: list[CaseResult]
    failed: list[str] = field(default_factory=list)
    waiting: list[Waiting] = field(default_factory=list)
    answered: int = 0
    correct: int = 0
    cost_usd_mean: float | None = None
    seconds_mean: float | None = None


# ---------------------------------------------------------------- числа: эталон и слой

def golden_value(con: duckdb.DuckDBPyConnection, case: Case) -> float | dict:
    rows = con.execute(case.golden_sql).fetchall()
    if case.kind == "table":
        out = {r[0]: float(r[1]) for r in rows if r[1] is not None}
        if not out:
            raise ValueError("эталон вернул пустую таблицу")
        return out
    if not rows or rows[0][0] is None:
        raise ValueError("эталон вернул пусто")
    return float(rows[0][0])


def _to_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _metric(con, catalog: Catalog, metric: str, mq: dict) -> float | dict:
    q = MetricQuery(metric=metric, date_from=_to_date(mq["date_from"]), date_to=_to_date(mq["date_to"]),
                    group_by=tuple(mq.get("group_by") or ()), filters=dict(mq.get("filters") or {}))
    sql, params = compile_query(catalog, q)
    rows = con.execute(sql, params).fetchall()
    if q.group_by:
        return {r[0]: float(r[-1]) for r in rows}
    return float(rows[0][-1]) if rows and rows[0][-1] is not None else None


def layer_value(con: duckdb.DuckDBPyConnection, catalog: Catalog, case: Case) -> float | dict | None:
    """Что вернёт инструмент агента B: запрос к слою метрик пакета 01; «a / b» — отношение двух метрик."""
    mq = case.metric_query
    parts = metric_parts(mq["metric"])
    scale = float(mq.get("scale") or 1)
    values = [_metric(con, catalog, m, mq) for m in parts]
    if len(values) == 1:
        v = values[0]
        if isinstance(v, dict):
            return {k: x * scale for k, x in v.items()}
        return None if v is None else v * scale
    num, den = values
    if isinstance(num, dict):
        return {k: scale * num[k] / den[k] for k in num if den.get(k)}
    return None if not den else scale * num / den


def _close(got, exp, tol) -> bool:
    if isinstance(exp, dict):
        return isinstance(got, dict) and got.keys() == exp.keys() and all(is_correct(got[k], exp[k], tol) for k in exp)
    return got is not None and is_correct(got, exp, tol)


# ---------------------------------------------------------------- ворота

def evaluate(con: duckdb.DuckDBPyConnection, catalog: Catalog, cases: list[Case], answers: dict[Key, Answer],
             variant: str, layer: bool, works_when: dict) -> Verdict:
    results: list[CaseResult] = []
    used: list[Answer] = []
    failed: list[str] = []
    waiting: list[Waiting] = []
    not_ready, no_golden, layer_bad = [], [], []

    for c in cases:
        r = CaseResult(c.id, c.from_q, c.covers, c.kind, c.question)
        results.append(r)
        tol = c.tolerance_pct
        if c.todo:
            r.status = "не готов"
            not_ready.append(c.id)
            continue
        try:
            r.expected = golden_value(con, c)
        except Exception as e:  # эталон, который не считается, — провал G2, а не падение прогона
            r.status, r.error = "нет эталона", f"{type(e).__name__}: {e}"
            no_golden.append(c.id)
            continue
        if layer:
            try:
                r.layer = layer_value(con, catalog, c)
                r.layer_ok = _close(r.layer, r.expected, tol)
            except Exception as e:
                r.layer_ok, r.error = False, f"{type(e).__name__}: {e}"
            if not r.layer_ok:
                layer_bad.append(c.id)
        if c.kind == "table":
            r.rows_total = len(r.expected)
            wrong = False
            for k, exp in r.expected.items():
                q = c.row_question.format(key=k)
                a = answers.get((variant, q))
                if a is None:
                    sql = f"SELECT v FROM ({c.golden_sql}) AS t(k, v) WHERE k = {k!r}"
                    mq = dict(c.metric_query or {})
                    mq.pop("group_by", None)
                    mq["filters"] = {**mq.get("filters", {}), c.metric_query["group_by"][0]: [k]}
                    waiting.append(Waiting(c.id, q, sql, mq))
                    continue
                used.append(a)
                r.rows_answered += 1
                if is_correct(a.value, exp, tol):
                    r.rows_correct += 1
                else:
                    wrong = True
            r.status = "ошибка" if wrong else ("ждёт прогона" if r.rows_answered < r.rows_total else "верно")
        else:
            a = answers.get((variant, c.question))
            if a is None:
                r.status = "ждёт прогона"
                waiting.append(Waiting(c.id, c.question, c.golden_sql, c.metric_query))
            else:
                used.append(a)
                r.answer = a.value
                r.status = "верно" if is_correct(a.value, r.expected, tol) else "ошибка"
        if r.status == "ошибка":
            failed.append(c.id)

    gates = {
        "G1": Gate(FAIL, "не готовы: " + ", ".join(not_ready)) if not_ready else Gate(PASS),
        "G2": Gate(FAIL, "эталон не считается: " + ", ".join(no_golden)) if no_golden else Gate(PASS),
        "G3": (Gate(NA, "у прототипа нет слоя метрик: числа проверяются только через ответы агента") if not layer
               else Gate(FAIL, "слой расходится с эталоном: " + ", ".join(layer_bad)) if layer_bad else Gate(PASS)),
    }
    if failed:
        gates["G4"] = Gate(FAIL, "ошибки агента: " + ", ".join(failed))
    elif waiting and works_when.get("every_case_answered", True):
        gates["G4"] = Gate(WAIT, f"нет ответа агента: {len(waiting)} из {len(waiting) + len(used)}")
    else:
        gates["G4"] = Gate(PASS)

    cost = sum(a.cost_usd for a in used) / len(used) if used else None
    secs = sum(a.seconds for a in used) / len(used) if used else None
    if not used:
        gates["G5"] = Gate(WAIT, "нет ни одного ответа агента")
    else:
        over = []
        if cost > works_when.get("max_cost_usd", float("inf")):
            over.append(f"цена ${cost:.4f} > ${works_when['max_cost_usd']}")
        if secs > works_when.get("max_seconds", float("inf")):
            over.append(f"время {secs:.1f} с > {works_when['max_seconds']} с")
        gates["G5"] = Gate(FAIL, "; ".join(over)) if over else Gate(PASS, f"${cost:.4f} и {secs:.1f} с на ответ")

    statuses = [g.status for g in gates.values()]
    verdict = "не принят" if FAIL in statuses else ("ждёт прогона" if WAIT in statuses else "принят")
    correct = sum(r.rows_correct if r.kind == "table" else int(r.status == "верно") for r in results)
    return Verdict(variant, verdict, gates, results, failed, waiting, len(used), correct, cost, secs)
