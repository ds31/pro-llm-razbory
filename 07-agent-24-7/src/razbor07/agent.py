"""Агент как генератор операций и три конфигурации запуска.

Агент отвечает магазину на вопрос: план и SQL (вызов модели) → запрос в витрину → ответ и вызов
инструмента send_reply (вызов модели) → письмо магазину → итог в журнал (третий вызов модели — так
устроен цикл tool use: после результата инструмента модель вызывают ещё раз). Агент не ждёт и не
ходит в сеть сам: он отдаёт операции (Call, Tool, Send, Sleep), а исполняет их среда — симулятор
с виртуальными часами или воркер в проде. Поэтому одна и та же логика проверяется прогоном на
1 000 задач за секунды и работает в docker compose.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Generator

from .fakellm import Outcome


@dataclass(frozen=True)
class Config:
    name: str
    title: str
    queue: bool                 # задачи через очередь и воркеры, а не синхронно в обработчике API
    idempotent: bool            # ключ на постановке в очередь и на отправке письма
    call_timeout: float         # таймаут одного вызова модели, с
    sdk_retries: int = 2        # повторы внутри вызова, как в SDK по умолчанию
    workers: int = 4            # воркеров (для очереди)
    lease: float = 60.0         # аренда задачи, с
    heartbeat: float = 15.0     # продление аренды, с
    max_attempts: int = 6       # попыток задачи до dead-letter
    backoff_base: float = 2.0
    backoff_cap: float = 300.0


# Наивная: как пишут демо — обработчик API зовёт агента синхронно, SDK с настройками по умолчанию
# (2 повтора, таймаут 10 минут), очереди, ретраев задачи и идемпотентности нет.
NAIVE = Config("naive", "Наивная: синхронно из API", queue=False, idempotent=False, call_timeout=600.0)
# Очередь, ретраи с backoff и dead-letter — но без ключей идемпотентности.
QUEUE = Config("queue", "Очередь и ретраи без идемпотентности", queue=True, idempotent=False, call_timeout=30.0)
# Прод: очередь, ретраи, dead-letter, ключ идемпотентности на постановке и на письме, таймаут 30 с.
PROD = Config("prod", "Прод: очередь, ретраи, идемпотентность", queue=True, idempotent=True, call_timeout=30.0)
CONFIGS = {c.name: c for c in (NAIVE, QUEUE, PROD)}

STEPS = ("plan", "answer", "finish")
SQL_SECONDS, SEND_SECONDS = 0.3, 0.4


@dataclass(frozen=True)
class Call:
    step: str
    timeout: float
    try_no: int


@dataclass(frozen=True)
class Tool:
    name: str
    seconds: float


@dataclass(frozen=True)
class Send:
    task_key: str
    idem_key: str | None
    seconds: float = SEND_SECONDS


@dataclass(frozen=True)
class Sleep:
    seconds: float


class ModelError(Exception):
    def __init__(self, kind: str, retryable: bool, retry_after: float | None, step: str):
        super().__init__(f"{kind} на шаге {step}")
        self.kind, self.retryable, self.retry_after, self.step = kind, retryable, retry_after, step


Op = Call | Tool | Send | Sleep


def _llm(step: str, cfg: Config, r: random.Random) -> Generator[Op, Outcome, Outcome]:
    """Вызов модели с повторами в стиле SDK: retry-after провайдера или 0,5·2^n с, не больше 8 с."""
    for try_no in range(cfg.sdk_retries + 1):
        res = yield Call(step, cfg.call_timeout, try_no)
        if res.kind == "ok":
            return res
        if not res.retryable or try_no == cfg.sdk_retries:
            raise ModelError(res.kind, res.retryable, res.retry_after, step)
        delay = res.retry_after if res.retry_after else min(0.5 * 2 ** try_no, 8.0) * (1 - 0.25 * r.random())
        yield Sleep(delay)
    raise AssertionError("недостижимо")


def agent_run(task_key: str, cfg: Config, r: random.Random) -> Generator[Op, Outcome | None, None]:
    yield from _llm("plan", cfg, r)
    yield Tool("sql", SQL_SECONDS)
    yield from _llm("answer", cfg, r)
    yield Send(task_key, f"{task_key}:reply" if cfg.idempotent else None)
    yield from _llm("finish", cfg, r)
