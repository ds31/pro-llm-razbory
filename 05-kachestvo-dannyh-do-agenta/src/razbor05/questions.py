"""Вопросы «за последний месяц»: шесть из группы «незакрытый месяц» eval пакета 01 и три новых.

«Последний месяц» = месяц `closed_through`. Ответ — эталонный запрос к слою метрик пакета 01 (`compile_query`),
то есть ровно то, что делает агент B, когда верно читает `closed_through`. Правда — тот же запрос к витринам,
собранным из того, что было на самом деле.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from razbor01.golden import is_correct
from razbor01.metrics import Catalog, MetricError, MetricQuery, compile_query, load_catalog

from .rules import PACKAGE_ROOT

METRICS_YAML = PACKAGE_ROOT / "metrics.yaml"


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(m: date, k: int) -> date:
    y, mm = divmod(m.month - 1 + k, 12)
    return date(m.year + y, mm + 1, 1)


def month_end(m: date) -> date:
    return add_months(m, 1) - timedelta(1)


class Ask:
    """Запрос к слою метрик на одном соединении с заданным closed_through."""

    def __init__(self, con, catalog: Catalog):
        self.con, self.catalog = con, catalog

    def rows(self, metric: str, date_from: date, date_to: date, group_by=(), filters=None) -> list[tuple]:
        sql, params = compile_query(self.catalog, MetricQuery(metric, date_from, date_to, tuple(group_by),
                                                              filters or {}))
        return self.con.execute(sql, params).fetchall()

    def value(self, metric: str, date_from: date, date_to: date, **kw) -> float | None:
        rows = self.rows(metric, date_from, date_to, **kw)
        return None if not rows or rows[0][-1] is None else float(rows[0][-1])


def _div(a, b):
    return None if a is None or not b else a / b


@dataclass(frozen=True)
class Question:
    id: str
    source: str            # «01» — вопрос группы open_month пакета 01; «05» — новый
    text: str
    fn: Callable[[Ask, date], float | None]


def _q20(a: Ask, m: date):
    return _div(a.value("revenue", add_months(m, -5), month_end(m)), 6)


def _q21(a: Ask, m: date):
    cur, prev = a.value("revenue", m, month_end(m)), a.value("revenue", add_months(m, -1), month_end(add_months(m, -1)))
    return None if cur is None or not prev else 100.0 * (cur / prev - 1)


def _q22(a: Ask, m: date):
    rows = a.rows("revenue", date(m.year, 1, 1), month_end(m), group_by=("month",))
    rows = [r for r in rows if r[1] is not None]
    return float(min(rows, key=lambda r: r[1])[0].month) if rows else None


QUESTIONS = [
    Question("Q19", "01", "Какая выручка сети за последний месяц, в рублях?",
             lambda a, m: a.value("revenue", m, month_end(m))),
    Question("Q20", "01", "Какая среднемесячная выручка сети за последние шесть месяцев, в рублях?", _q20),
    Question("Q21", "01", "На сколько процентов выручка сети за последний месяц выше или ниже, чем за предыдущий? "
             "Ответ — число процентов, со знаком минус при падении.", _q21),
    Question("Q22", "01", "Какой месяц 2026 года был для сети самым слабым по выручке? Ответ — номер месяца.", _q22),
    Question("Q23", "01", "Какая выручка магазинов региона «Восток» за последний месяц, в рублях?",
             lambda a, m: a.value("revenue", m, month_end(m), filters={"region": ["Восток"]})),
    Question("Q24", "01", "Сколько единиц товара категории «Заморозка» продано за последний месяц?",
             lambda a, m: a.value("units", m, month_end(m), filters={"category": ["Заморозка"]})),
    Question("N1", "05", "Какая выручка магазина №4 за последний месяц, в рублях?",
             lambda a, m: a.value("revenue", m, month_end(m), filters={"store_id": [4]})),
    Question("N2", "05", "Сколько единиц товара на остатках сети на конец последнего месяца?",
             lambda a, m: a.value("stock_end_units", m, month_end(m))),
    Question("N3", "05", "Какая выручка категории «Напитки» за последний месяц, в рублях?",
             lambda a, m: a.value("revenue", m, month_end(m), filters={"category": ["Напитки"]})),
]


def catalog(closed_through: date, path: Path | str = METRICS_YAML) -> Catalog:
    return replace(load_catalog(path), closed_through=closed_through)


def answer_all(con, closed_through: date) -> dict[str, float | None]:
    """Ответы на все вопросы для «последнего месяца» = месяц closed_through."""
    ask = Ask(con, catalog(closed_through))
    m = month_start(closed_through)
    out = {}
    for q in QUESTIONS:
        try:
            out[q.id] = q.fn(ask, m)
        except MetricError:
            out[q.id] = None
    return out


def revenue_of(con, closed_through: date, month: date) -> float | None:
    try:
        return Ask(con, catalog(closed_through)).value("revenue", month, month_end(month))
    except MetricError:
        return None


def score(got: dict, truth: dict) -> dict[str, bool]:
    return {qid: truth[qid] is not None and is_correct(got.get(qid), truth[qid]) for qid in truth}
