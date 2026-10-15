"""Шлюз SQL: один SELECT и только таблицы из разрешённых схем."""
from __future__ import annotations

import duckdb


class SqlRejected(ValueError):
    """Запрос не пропущен шлюзом; текст ошибки уходит агенту как подсказка."""


def check_sql(con: duckdb.DuckDBPyConnection, sql: str, allowed_schemas: set[str]) -> None:
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as e:
        raise SqlRejected(f"SQL не разобран: {e}") from e
    if len(statements) != 1:
        raise SqlRejected("нужен ровно один запрос")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise SqlRejected("разрешён только SELECT")
    try:
        tables = con.get_table_names(sql, qualified=True)
    except duckdb.ParserException as e:
        raise SqlRejected(f"SQL не разобран: {e}") from e
    except duckdb.Error as e:
        raise SqlRejected(f"запрос отклонён: {str(e).splitlines()[0]}") from e
    allowed_schemas = {s.lower() for s in allowed_schemas}
    bad = sorted(t for t in tables if "." not in t or t.split(".")[0].strip('"').lower() not in allowed_schemas)
    if bad:
        allowed = ", ".join(f"{s}.*" for s in sorted(allowed_schemas))
        raise SqlRejected(f"таблицы {', '.join(bad)} недоступны; пишите имя со схемой, доступно: {allowed}")
