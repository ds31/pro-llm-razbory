"""Счётчик над клиентом Messages API: токены, рассуждение и списанная цена каждого вызова.

Агент пакета 01 шлёт output_config={"effort": "medium"}. Через OpenRouter этот параметр принимают
и модели не от Anthropic (проверено 21.10.2026 на deepseek-v4.1-flash, glm-5.3, gpt-5.6-luna), но
он меняет их поведение: например, glm-5.3 с ним начинает рассуждать. Поэтому параметр задаётся здесь,
одним значением для всех моделей прогона: effort=None убирает его из запроса совсем.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass
class CallUsage:
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    cache_read_tokens: int = 0
    billed_usd: float | None = None   # usage.cost от OpenRouter; у Anthropic напрямую его нет
    seconds: float = 0.0


def _int(v) -> int:
    return int(v) if isinstance(v, (int, float)) else 0


def _get(obj, name):
    """Поле ответа: SDK отдаёт незнакомые ему поля OpenRouter то атрибутом, то словарём."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


class MeteredClient:
    def __init__(self, inner, effort: str | None = "medium", clock=time.perf_counter):
        self._inner, self.effort, self._clock = inner, effort, clock
        self._calls: list[CallUsage] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        kw.pop("output_config", None)
        if self.effort:
            kw["output_config"] = {"effort": self.effort}
        t0 = self._clock()
        resp = self._inner.messages.create(**kw)
        u = resp.usage
        cost = _get(u, "cost")
        self._calls.append(CallUsage(
            input_tokens=_int(_get(u, "input_tokens")),
            output_tokens=_int(_get(u, "output_tokens")),
            thinking_tokens=_int(_get(_get(u, "output_tokens_details"), "thinking_tokens")),
            cache_read_tokens=_int(_get(u, "cache_read_input_tokens")),
            billed_usd=float(cost) if isinstance(cost, (int, float)) else None,
            seconds=self._clock() - t0))
        return resp

    def take(self) -> list[CallUsage]:
        """Вызовы с прошлого take() — счётчик одного ответа агента."""
        calls, self._calls = self._calls, []
        return calls
