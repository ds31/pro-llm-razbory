from pathlib import Path

import pytest

from razbor05.feed import build_base

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def base(tmp_path_factory) -> Path:
    return build_base(tmp_path_factory.mktemp("data") / "base.duckdb")
