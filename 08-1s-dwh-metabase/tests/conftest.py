from datetime import date

import pytest

from razbor08.source import Source1C, Volume

TINY = Volume(name="T", stores=3, skus=40, history_days=60, lines=5)
START = date(2026, 10, 19)


@pytest.fixture
def src():
    s = Source1C.create(":memory:", TINY, sim_start=START, seed=8)
    yield s
    s.close()
