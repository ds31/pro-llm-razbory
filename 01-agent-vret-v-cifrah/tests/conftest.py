from pathlib import Path

import pytest

from razbor01.layers import prepare_db
from razbor01.tools import open_db

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> Path:
    return prepare_db(tmp_path_factory.mktemp("data") / "retail.duckdb")


@pytest.fixture(scope="session")
def con(db_path):
    c = open_db(db_path)
    yield c
    c.close()
