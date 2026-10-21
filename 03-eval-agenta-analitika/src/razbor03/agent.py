"""Агент под проверкой. Здесь — адаптер к агенту пакета 01 (варианты A и B).

Чтобы проверить своего агента, напишите такой же класс с методом answer(question) -> Answer
и передайте фабрику в CLI: `--agent mypkg.myagent:make`. Фабрика получает именованные
аргументы con, catalog, variant, model, client и может их игнорировать.
"""
from __future__ import annotations

import importlib

from razbor01.agent import PRICES as PRICES_01
from razbor01.agent import run_agent
from razbor01.tools import make_toolbox

from .runs import Answer

# $ за 1M токенов (вход, выход). Источник — прайс OpenRouter на 2026-10-21; Anthropic — как в пакете 01.
PRICES = dict(PRICES_01)


def price(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES[model]
    return input_tokens * pin / 1e6 + output_tokens * pout / 1e6


class DemoAgent:
    """Агент пакета 01: тот же цикл tool use, инструменты варианта A (сырые таблицы) или B (слой метрик)."""

    def __init__(self, con, catalog, variant: str, model: str, client):
        self.box = make_toolbox(variant, con, catalog)
        self.model = model
        self.client = client

    def answer(self, question: str) -> Answer:
        r = run_agent(question, self.box, self.client, model=self.model)
        trace = [{"name": c.name, "input": c.input, "output": c.output, "is_error": c.is_error} for c in r.trace]
        return Answer(qid="", value=r.value, unit=r.unit, explanation=r.explanation, trace=trace,
                      cost_usd=round(r.cost_usd(self.model), 6), seconds=round(r.seconds, 2), stop=r.stop)


def make(*, con, catalog, variant: str, model: str, client, **_) -> DemoAgent:
    return DemoAgent(con, catalog, variant, model, client)


def load_factory(spec: str):
    """'модуль:функция' → фабрика агента."""
    module, _, func = spec.partition(":")
    if not module or not func:
        raise ValueError(f"--agent ждёт 'модуль:функция', получено {spec!r}")
    return getattr(importlib.import_module(module), func)
