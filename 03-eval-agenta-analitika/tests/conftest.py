from pathlib import Path

import pytest

from razbor03.scenarios import build_data

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    """Все базы сценариев: base, reload, no-anomaly-rule — один раз на сессию."""
    d = tmp_path_factory.mktemp("data")
    build_data(d)
    return d
