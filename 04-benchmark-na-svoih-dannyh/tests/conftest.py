from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from razbor01.golden import load_questions
from razbor01.layers import prepare_db
from razbor01.metrics import load_catalog
from razbor01.tools import open_db
from razbor04.paths import BASE

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = load_questions(BASE / "eval" / "questions.yaml")
CATALOG = load_catalog(BASE / "metrics.yaml")


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> Path:
    return prepare_db(tmp_path_factory.mktemp("data") / "retail.duckdb")


@pytest.fixture(scope="session")
def con(db_path):
    c = open_db(db_path)
    yield c
    c.close()


def usage(tin=1000, tout=100, cost=None, thinking=0, cache_read=0):
    u = NS(input_tokens=tin, output_tokens=tout, cache_read_input_tokens=cache_read,
           output_tokens_details=NS(thinking_tokens=thinking))
    if cost is not None:
        u.cost = cost
    return u


def tool_use(i, name, args):
    return NS(type="tool_use", id=i, name=name, input=args)


def reply(blocks, stop="tool_use", **kw):
    return NS(content=blocks, stop_reason=stop, usage=usage(**kw))


class ScriptClient:
    """Отдаёт заготовленные ответы модели и запоминает запросы. В API не ходит."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
