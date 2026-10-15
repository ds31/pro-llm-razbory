"""Инструменты агента для двух вариантов эксперимента.

A — сырые таблицы: list_tables, describe_table, run_sql (схема raw).
B — платформа: list_metrics, describe_metric, query_metric, run_sql (схема mart).
У обоих — final_answer: агент сдаёт число, цикл на нём останавливается.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from .guard import SqlRejected, check_sql
from .metrics import Catalog, MetricError, MetricQuery, compile_query

MAX_ROWS = 50


def open_db(path: Path | str) -> duckdb.DuckDBPyConnection:
    """Единственный способ открыть базу для агента: только чтение и без доступа к файлам и сети.

    Шлюз SQL пропускает табличные функции вроде read_text('.env'); их закрывает именно это соединение.
    """
    return duckdb.connect(str(path), read_only=True, config={"enable_external_access": False})

SYSTEM_A = (
    "Ты аналитик розничной сети. Данные — в DuckDB, схема raw: продажи, остатки, справочники. "
    "Отвечай на вопрос одним числом. Сначала изучи таблицы, затем посчитай через run_sql. "
    "Когда число готово, вызови final_answer. Не округляй: для долей и процентов — минимум два знака после запятой."
)
SYSTEM_B = (
    "Ты аналитик розничной сети. Отвечай через слой метрик: list_metrics → describe_metric → query_metric. "
    "Правила компании возвращает list_metrics — соблюдай их. run_sql — только по витринам mart.*, "
    "когда нужной метрики нет. Отвечай одним числом через final_answer и укажи metric_id, на который опирался. "
    "Не округляй: для долей и процентов — минимум два знака после запятой."
)

FINAL_ANSWER = {
    "name": "final_answer",
    "description": "Сдать ответ. Вызывается один раз, в конце.",
    "input_schema": {
        "type": "object",
        "properties": {
            "value": {"type": "number", "description": "Ответ числом, без округления."},
            "unit": {"type": "string", "description": "Единица: ₽, шт., %, номер магазина, номер месяца."},
            "explanation": {"type": "string", "description": "Как посчитано, одним-двумя предложениями."},
            "metric_id": {"type": "string", "description": "Метрика слоя метрик, если использовалась."},
        },
        "required": ["value", "unit", "explanation"],
    },
}
RUN_SQL = {
    "name": "run_sql",
    "description": "Выполнить один SELECT в DuckDB. Возвращает до 50 строк в JSON.",
    "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
}
SPECS_A = [
    {"name": "list_tables", "description": "Список таблиц схемы raw с числом строк.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "describe_table", "description": "Колонки и типы таблицы, например raw.sales.",
     "input_schema": {"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]}},
    RUN_SQL, FINAL_ANSWER,
]
SPECS_B = [
    {"name": "list_metrics", "description": "Метрики, измерения, правила компании и дата закрытия данных.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "describe_metric", "description": "Описание метрики: формула, таблица, измерения, правило времени.",
     "input_schema": {"type": "object", "properties": {"metric_id": {"type": "string"}}, "required": ["metric_id"]}},
    {"name": "query_metric",
     "description": "Посчитать метрику за период [date_from; date_to] (YYYY-MM-DD, включительно), "
                    "с разрезами group_by и фильтрами filters {измерение: [значения]}. Возвращает строки и SQL.",
     "input_schema": {"type": "object", "properties": {
         "metric_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"},
         "group_by": {"type": "array", "items": {"type": "string"}},
         "filters": {"type": "object", "additionalProperties": {"type": "array", "items": {}}}},
         "required": ["metric_id", "date_from", "date_to"]}},
    RUN_SQL, FINAL_ANSWER,
]


def _default(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    raise TypeError(f"{type(v).__name__} не сериализуется в JSON")


def _json(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, default=_default)


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> tuple[list[dict], bool]:
    """До MAX_ROWS строк и признак, что результат был длиннее."""
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    got = [dict(zip(cols, r)) for r in cur.fetchmany(MAX_ROWS + 1)]
    return got[:MAX_ROWS], len(got) > MAX_ROWS


TRUNC_HINT = f"показаны первые {MAX_ROWS} строк; агрегируйте в SQL"


def _result(rows: list[dict], truncated: bool) -> str:
    if not truncated:
        return _json(rows)
    return json.dumps({"rows": rows, "truncated": True, "hint": TRUNC_HINT}, ensure_ascii=False, default=_default)


@dataclass
class ToolBox:
    variant: str
    system: str
    specs: list[dict]
    con: duckdb.DuckDBPyConnection
    catalog: Catalog | None = None

    def call(self, name: str, args: dict) -> tuple[str, bool]:
        """Выполнить инструмент. Возвращает (текст результата, is_error)."""
        allowed = {s["name"] for s in self.specs} - {"final_answer"}
        if name not in allowed:
            return f"Ошибка: нет инструмента {name}; доступны: {', '.join(sorted(allowed))}", True
        try:
            return getattr(self, f"_{name}")(**args), False
        except (SqlRejected, MetricError, duckdb.Error, TypeError, ValueError) as e:
            return f"Ошибка: {e}", True

    # --- общий
    def _run_sql(self, sql: str) -> str:
        check_sql(self.con, sql, {"raw"} if self.variant == "A" else {"mart"})
        return _result(*_rows(self.con, sql))

    # --- вариант A
    def _list_tables(self) -> str:
        rows, _ = _rows(self.con, "SELECT schema_name || '.' || table_name AS table, estimated_size AS rows "
                               "FROM duckdb_tables() WHERE schema_name = 'raw' ORDER BY 1")
        return _json(rows)

    def _describe_table(self, table: str) -> str:
        schema, _, name = table.partition(".")
        if schema != "raw":
            raise ValueError("доступна только схема raw")
        rows, _ = _rows(self.con, "SELECT column_name, data_type FROM duckdb_columns() "
                               "WHERE schema_name = ? AND table_name = ? ORDER BY column_index", [schema, name])
        if not rows:
            raise ValueError(f"нет таблицы {table}")
        return _json(rows)

    # --- вариант B
    def _list_metrics(self) -> str:
        cat = self.catalog
        return json.dumps({
            "closed_through": cat.closed_through.isoformat(),
            "rules": list(cat.rules),
            "dimensions": cat.dimensions,
            "metrics": [{"id": m.id, "label": m.label, "description": m.description,
                         "dimensions": list(m.dimensions)} for m in cat.metrics.values()],
        }, ensure_ascii=False)

    def _describe_metric(self, metric_id: str) -> str:
        m = self.catalog.metrics.get(metric_id)
        if m is None:
            raise MetricError(f"нет метрики {metric_id}")
        return json.dumps({"id": m.id, "label": m.label, "description": m.description, "table": m.table,
                           "expr": m.expr, "time_rule": m.time_rule, "dimensions": list(m.dimensions),
                           "synonyms": list(m.synonyms)}, ensure_ascii=False)

    def _query_metric(self, metric_id: str, date_from: str, date_to: str,
                      group_by: list[str] | None = None, filters: dict | None = None) -> str:
        q = MetricQuery(metric=metric_id, date_from=date.fromisoformat(date_from),
                        date_to=date.fromisoformat(date_to), group_by=tuple(group_by or ()),
                        filters=dict(filters or {}))
        sql, params = compile_query(self.catalog, q)
        rows, truncated = _rows(self.con, sql, params)
        out = {"metric_id": metric_id, "sql": sql, "params": [str(p) for p in params], "rows": rows,
               "truncated": truncated}
        if truncated:
            out["hint"] = TRUNC_HINT
        return json.dumps(out, ensure_ascii=False, default=_default)


def make_toolbox(variant: str, con: duckdb.DuckDBPyConnection, catalog: Catalog | None = None) -> ToolBox:
    if variant == "A":
        return ToolBox("A", SYSTEM_A, SPECS_A, con)
    if variant == "B":
        if catalog is None:
            raise ValueError("варианту B нужен каталог метрик")
        return ToolBox("B", SYSTEM_B, SPECS_B, con, catalog)
    raise ValueError(f"неизвестный вариант {variant}")
