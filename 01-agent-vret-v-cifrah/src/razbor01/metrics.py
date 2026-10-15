"""Слой метрик: загрузка metrics.yaml и компиляция запроса метрики в SQL с параметрами."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

TIME_RULES = {"range", "period_end", "period_avg"}


class MetricError(ValueError):
    """Запрос к слою метрик нарушает правила (неизвестная метрика, измерение, период)."""


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    description: str
    table: str
    time_column: str
    time_rule: str
    expr: str
    dimensions: tuple[str, ...]
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class Catalog:
    closed_through: date
    rules: tuple[dict, ...]
    dimensions: dict[str, dict]
    metrics: dict[str, Metric]


@dataclass(frozen=True)
class MetricQuery:
    metric: str
    date_from: date
    date_to: date
    group_by: tuple[str, ...] = ()
    filters: dict[str, list] = field(default_factory=dict)


def load_catalog(path: Path | str) -> Catalog:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    dims = raw["dimensions"]
    metrics = {}
    for m in raw["metrics"]:
        metric = Metric(id=m["id"], label=m["label"], description=m["description"], table=m["table"],
                        time_column=m["time_column"], time_rule=m["time_rule"], expr=m["expr"],
                        dimensions=tuple(m["dimensions"]), synonyms=tuple(m.get("synonyms", [])))
        if metric.time_rule not in TIME_RULES:
            raise MetricError(f"{metric.id}: неизвестное time_rule {metric.time_rule}")
        unknown = set(metric.dimensions) - set(dims)
        if unknown:
            raise MetricError(f"{metric.id}: неизвестные измерения {sorted(unknown)}")
        if metric.id in metrics:
            raise MetricError(f"дубль метрики {metric.id}")
        metrics[metric.id] = metric
    return Catalog(closed_through=date.fromisoformat(str(raw["closed_through"])),
                   rules=tuple(raw["rules"]), dimensions=dims, metrics=metrics)


def compile_query(cat: Catalog, q: MetricQuery) -> tuple[str, list]:
    """Вернуть (sql, params). Колонка результата с числом называется value."""
    if q.metric not in cat.metrics:
        raise MetricError(f"нет метрики {q.metric}; доступны: {', '.join(sorted(cat.metrics))}")
    m = cat.metrics[q.metric]
    if q.date_from > q.date_to:
        raise MetricError("date_from позже date_to")
    if q.date_to > cat.closed_through:
        raise MetricError(f"период заходит в незакрытый месяц: данные закрыты по {cat.closed_through.isoformat()}")
    for d in list(q.group_by) + list(q.filters):
        if d not in m.dimensions:
            raise MetricError(f"метрика {m.id} не режется по {d}; можно: {', '.join(m.dimensions)}")
    if len(set(q.group_by)) != len(q.group_by):
        raise MetricError(f"group_by содержит повторы: {', '.join(q.group_by)}")
    for d, values in q.filters.items():
        if values is None or (isinstance(values, list) and (None in values)):
            raise MetricError(f"фильтр по {d} содержит null: укажите значения или уберите фильтр")
        if isinstance(values, list) and not values:
            raise MetricError(f"фильтр по {d} пуст: укажите значения или уберите фильтр")
    params: list = [q.date_from, q.date_to]
    where = [f"{m.time_column} BETWEEN ? AND ?"]
    for d, values in q.filters.items():
        values = values if isinstance(values, list) else [values]
        where.append(f"{d} IN ({', '.join('?' for _ in values)})")
        params.extend(values)
    dims = ", ".join(q.group_by)
    sel = f"{dims}, " if dims else ""
    grp = f" GROUP BY {dims} ORDER BY {dims}" if dims else ""
    cond = " AND ".join(where)
    if m.time_rule == "range":
        sql = f"SELECT {sel}{m.expr} AS value FROM {m.table} WHERE {cond}{grp}"
    elif m.time_rule == "period_end":
        sql = (f"SELECT {sel}{m.expr} AS value FROM {m.table} WHERE {cond} AND {m.time_column} = "
               f"(SELECT max({m.time_column}) FROM {m.table} WHERE {m.time_column} BETWEEN ? AND ?){grp}")
        params += [q.date_from, q.date_to]
    else:  # period_avg
        inner_dims = f"{m.time_column}, {dims}" if dims else m.time_column
        sql = (f"SELECT {sel}avg(v) AS value FROM (SELECT {inner_dims}, {m.expr} AS v FROM {m.table} "
               f"WHERE {cond} GROUP BY {inner_dims}){grp}")
    return sql, params
