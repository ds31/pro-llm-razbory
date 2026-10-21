"""Цены моделей: $ за 1M токенов (вход, выход).

Источник — прайс OpenRouter (https://openrouter.ai/models) на 2026-10-21. Новая модель — скилл add-model.
Это цена по прайсу. Сколько списал OpenRouter на самом деле (поле usage.cost), пишется отдельно:
у моделей с открытыми весами запрос уходит одному из нескольких провайдеров, и у них разные цены.
"""
from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    "anthropic/claude-opus-5.5": (4.00, 20.00),
    "anthropic/claude-sonnet-5.5": (2.00, 10.00),
    "anthropic/claude-haiku-5.5": (0.10, 0.50),
    "deepseek/deepseek-v4.1-flash": (0.06, 0.12),
    "z-ai/glm-5.3": (0.08, 1.40),
    "openai/gpt-5.6-luna": (0.20, 1.20),
}

DEFAULT_MODELS = ["anthropic/claude-opus-5.5", "anthropic/claude-sonnet-5.5",
                  "anthropic/claude-haiku-5.5", "deepseek/deepseek-v4.1-flash"]


class UnknownModel(KeyError):
    def __str__(self) -> str:
        return (f"нет цены для модели {self.args[0]}: добавьте её в PRICES (src/razbor04/prices.py), "
                f"скилл add-model")


def price(model: str) -> tuple[float, float]:
    try:
        return PRICES[model]
    except KeyError:
        raise UnknownModel(model) from None


def list_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = price(model)
    return input_tokens * pin / 1e6 + output_tokens * pout / 1e6


def order(model: str) -> int:
    """Порядок в отчёте — как в PRICES (от дорогих к дешёвым), незнакомые модели — в конце."""
    keys = list(PRICES)
    return keys.index(model) if model in keys else len(keys)


def slug(model: str) -> str:
    return model.replace("/", "__")


def short(model: str) -> str:
    return model.split("/", 1)[-1]
