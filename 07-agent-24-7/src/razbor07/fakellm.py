"""Фейковая модель вместо живого LLM: задержка, токены и сбои по профилю, детерминированно по seed.

Каждый вызов получает свой генератор случайных чисел из (seed, задача, метка вызова), поэтому
одна и та же попытка одной и той же задачи ведёт себя одинаково в любой конфигурации.
Лимит запросов в минуту общий на ключ: сверх лимита — 429 с retry-after, как у провайдеров.
"""
from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass

RETRYABLE = frozenset({"rate_limited", "overloaded", "hang", "timeout", "drop"})


@dataclass(frozen=True)
class Faults:
    rpm_limit: int = 50            # запросов в минуту на ключ; сверх — 429 с retry-after
    p_overload: float = 0.01       # 529 overloaded: перегрузка провайдера, без retry-after
    p_hang: float = 0.005          # вызов не возвращается: спасает только таймаут клиента
    p_drop: float = 0.01           # соединение рвётся посреди ответа
    p_poison: float = 0.005        # задача, на которой модель всегда отвечает 400 (битый вход)
    latency_median: float = 3.0    # секунды
    latency_sigma: float = 0.5     # разброс логнормальной задержки
    tokens_in: int = 1800
    tokens_out: int = 250


@dataclass(frozen=True)
class Outcome:
    kind: str                      # ok | rate_limited | overloaded | hang | drop | bad_request | timeout
    duration: float                # через сколько секунд вызов вернётся; inf — не вернётся
    retry_after: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE


def rng(seed: int, *label) -> random.Random:
    """Детерминированный генератор по метке: строковый seed не зависит от PYTHONHASHSEED."""
    return random.Random(f"{seed}:" + ":".join(str(x) for x in label))


class FakeModel:
    def __init__(self, faults: Faults, seed: int):
        self.f, self.seed = faults, seed
        self.window: deque[float] = deque()   # времена принятых вызовов за последние 60 с
        self.accepted = 0
        self.rejected = 0

    def is_poison(self, task_key: str) -> bool:
        return rng(self.seed, "poison", task_key).random() < self.f.p_poison

    def call(self, now: float, task_key: str, label: str) -> Outcome:
        f = self.f
        if self.is_poison(task_key):
            self.accepted += 1
            return Outcome("bad_request", 0.3, tokens_in=f.tokens_in)
        while self.window and self.window[0] <= now - 60.0:
            self.window.popleft()
        if len(self.window) >= f.rpm_limit:
            self.rejected += 1
            wait = self.window[0] + 60.0 - now if self.window else 60.0
            return Outcome("rate_limited", 0.2, retry_after=max(wait, 0.1))
        self.window.append(now)
        self.accepted += 1
        r = rng(self.seed, "call", task_key, label)
        latency = f.latency_median * math.exp(f.latency_sigma * r.gauss(0.0, 1.0))
        t_in = int(f.tokens_in * (0.8 + 0.4 * r.random()))
        t_out = int(f.tokens_out * (0.6 + 0.8 * r.random()))
        u, cut = r.random(), r.uniform(0.1, 0.9)
        if u < f.p_overload:
            return Outcome("overloaded", 0.5)
        u -= f.p_overload
        if u < f.p_hang:
            return Outcome("hang", math.inf, tokens_in=t_in)
        u -= f.p_hang
        if u < f.p_drop:
            return Outcome("drop", latency * cut, tokens_in=t_in, tokens_out=int(t_out * cut))
        return Outcome("ok", latency, tokens_in=t_in, tokens_out=t_out)
