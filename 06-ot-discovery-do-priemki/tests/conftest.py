import copy
from pathlib import Path

import pytest
import yaml

from razbor06.paths import PKG01, ROOT

EXAMPLES = ROOT / "examples" / "retail"


@pytest.fixture(scope="session")
def filled_raw() -> dict:
    return yaml.safe_load((EXAMPLES / "discovery.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def filled(filled_raw) -> dict:
    """Копия заполненного discovery, которую тест может портить."""
    return copy.deepcopy(filled_raw)


@pytest.fixture(scope="session")
def catalog_ids() -> set[str]:
    from razbor01.metrics import load_catalog
    return set(load_catalog(PKG01 / "metrics.yaml").metrics)


@pytest.fixture(scope="session")
def db(tmp_path_factory) -> Path:
    from razbor01.layers import prepare_db
    return prepare_db(tmp_path_factory.mktemp("data") / "retail.duckdb")
