"""Публикация витрин из DuckDB в Postgres, который читает Metabase.

Витрины заливаются в схему mart_load, затем одной транзакцией подменяют схему mart:
дашборды никогда не видят наполовину залитую таблицу. Нужен extra `pg`: `uv run --extra pg ...`.
"""
from __future__ import annotations

import re

MART_TABLES = ["sales_daily", "receipts_daily", "stock_month_end", "stock_current", "stores", "products"]

_SIMPLE = {"DATE": "date", "BIGINT": "bigint", "INTEGER": "integer", "VARCHAR": "text", "BOOLEAN": "boolean",
           "DOUBLE": "double precision", "TIMESTAMP": "timestamp", "HUGEINT": "numeric(38,0)"}


def pg_type(duck: str) -> str:
    if duck in _SIMPLE:
        return _SIMPLE[duck]
    m = re.fullmatch(r"DECIMAL\((\d+),(\d+)\)", duck)
    if m:
        return f"numeric({m.group(1)},{m.group(2)})"
    raise ValueError(f"нет соответствия типу DuckDB {duck}")


def _columns(wh, table: str) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in wh.con.execute(f"DESCRIBE mart.{table}").fetchall()]


def ddl(wh, table: str, schema: str = "mart_load") -> str:
    cols = ", ".join(f"{n} {pg_type(t)}" for n, t in _columns(wh, table))
    return f"CREATE TABLE {schema}.{table} ({cols})"


def publish(wh, dsn: str, batch: int = 50_000, reader: str = "metabase_reader") -> dict[str, int]:
    import psycopg  # extra pg

    counts: dict[str, int] = {}
    with psycopg.connect(dsn) as pg:
        pg.execute("DROP SCHEMA IF EXISTS mart_load CASCADE")
        pg.execute("CREATE SCHEMA mart_load")
        for t in MART_TABLES:
            pg.execute(ddl(wh, t))
            cols = [n for n, _ in _columns(wh, t)]
            cur = wh.con.execute(f"SELECT {', '.join(cols)} FROM mart.{t}")
            n = 0
            with pg.cursor().copy(f"COPY mart_load.{t} ({', '.join(cols)}) FROM STDIN") as cp:
                while rows := cur.fetchmany(batch):
                    for r in rows:
                        cp.write_row(r)
                    n += len(rows)
            counts[t] = n
        pg.execute("DROP SCHEMA IF EXISTS mart CASCADE")
        pg.execute("ALTER SCHEMA mart_load RENAME TO mart")
        # Metabase читает витрины пользователем только для чтения (deploy/initdb/01-roles.sh)
        if pg.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [reader]).fetchone():
            pg.execute(f"GRANT USAGE ON SCHEMA mart TO {reader}")
            pg.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA mart TO {reader}")
        pg.commit()
    return counts
