"""Мост к пакету 01: его слой метрик (metrics.yaml + compile_query) поверх витрин этого пакета.

Витрины mart.sales_daily и mart.stock_month_end повторяют колонки пакета 01, поэтому каталог
метрик и агент B пакета 01 подключаются без правок. Меняется только closed_through: в живой
платформе его выставляют ворота качества (пакет 05), здесь — параметром.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import razbor01
from razbor01.metrics import Catalog, MetricQuery, compile_query, load_catalog

METRICS_01 = Path(razbor01.__file__).resolve().parents[2] / "metrics.yaml"


def catalog_01(closed_through: date) -> Catalog:
    return dataclasses.replace(load_catalog(METRICS_01), closed_through=closed_through)


def metric(wh, metric_id: str, date_from: date, date_to: date, group_by: tuple[str, ...] = (),
           filters: dict | None = None, closed_through: date | None = None) -> list[tuple]:
    cat = catalog_01(closed_through or date_to)
    sql, params = compile_query(cat, MetricQuery(metric_id, date_from, date_to, tuple(group_by), filters or {}))
    return wh.con.execute(sql, params).fetchall()
