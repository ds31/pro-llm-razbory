"""Слои stg и mart поверх raw: правила компании в одном SQL-файле."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import duckdb

from .synth import generate


def build_layers(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(files("razbor01").joinpath("layers.sql").read_text(encoding="utf-8"))


def prepare_db(db_path: Path | str, seed: int | None = None) -> Path:
    """Сгенерировать raw и построить stg/mart. Возвращает путь к файлу базы."""
    path = generate(db_path) if seed is None else generate(db_path, seed=seed)
    con = duckdb.connect(str(path))
    try:
        build_layers(con)
    finally:
        con.close()
    return path
