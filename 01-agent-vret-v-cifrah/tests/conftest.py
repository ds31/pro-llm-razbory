from pathlib import Path

import duckdb
import pytest

from razbor01.synth import generate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> Path:
    return generate(tmp_path_factory.mktemp("data") / "retail.duckdb")


@pytest.fixture(scope="session")
def con(db_path):
    c = duckdb.connect(str(db_path), read_only=True)
    yield c
    c.close()
