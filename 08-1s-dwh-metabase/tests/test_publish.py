"""Публикация витрин в Postgres для Metabase: DDL без сервера, сама загрузка — если задан RAZBOR08_PG_DSN."""
import os
from datetime import timedelta

import pytest

from razbor08.dwh import Warehouse
from razbor08.publish import MART_TABLES, ddl, pg_type, publish
from razbor08.source import DocFilter, export_time

from .conftest import START


def test_pg_types():
    assert pg_type("DATE") == "date"
    assert pg_type("BIGINT") == "bigint"
    assert pg_type("INTEGER") == "integer"
    assert pg_type("DECIMAL(38,2)") == "numeric(38,2)"
    assert pg_type("VARCHAR") == "text"
    with pytest.raises(ValueError):
        pg_type("STRUCT(a INTEGER)")


def _wh(src, tmp_path):
    day = START - timedelta(days=1)
    wh = Warehouse(":memory:")
    src.export(tmp_path / "b", export_time(day), DocFilter.all())
    wh.load_batch(tmp_path / "b")
    wh.build_marts(day)
    return wh


def test_ddl_for_every_mart(src, tmp_path):
    wh = _wh(src, tmp_path)
    for t in MART_TABLES:
        sql = ddl(wh, t, schema="mart_load")
        assert sql.startswith(f"CREATE TABLE mart_load.{t} (")
    assert "net_amount numeric(38,2)" in ddl(wh, "sales_daily", schema="mart_load")
    wh.close()


@pytest.mark.skipif(not os.environ.get("RAZBOR08_PG_DSN"), reason="нужен Postgres: RAZBOR08_PG_DSN")
def test_publish_roundtrip(src, tmp_path):
    import psycopg
    wh = _wh(src, tmp_path)
    counts = publish(wh, os.environ["RAZBOR08_PG_DSN"])
    with psycopg.connect(os.environ["RAZBOR08_PG_DSN"]) as pg:
        for t, n in counts.items():
            assert pg.execute(f"SELECT count(*) FROM mart.{t}").fetchone()[0] == n
    wh.close()
