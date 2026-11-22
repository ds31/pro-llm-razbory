"""Структурный журнал: одна строка JSON на событие, в каждой — id задачи, попытка, воркер, время и цена.

По id задачи собирается трасса: когда пришла, кто взял, какие вызовы модели, сколько токенов и
денег, чем кончилась каждая попытка. Поля совместимы по смыслу с семантикой OpenTelemetry для
GenAI (gen_ai.usage.input_tokens / output_tokens) — журнал можно отправить в любой сборщик логов.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Пример цены за 1 млн токенов (вход, выход), USD. Подставьте цену своей модели.
PRICE_IN, PRICE_OUT = 3.0, 15.0

# Чем кончается попытка: без такого события попытка в трассе «оборвана».
TERMINAL = frozenset({"done", "retry_scheduled", "dead", "lease_expired", "request_error", "request_done",
                      "lost_lease"})
START = frozenset({"claimed", "request_start"})


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    return round((tokens_in * PRICE_IN + tokens_out * PRICE_OUT) / 1e6, 6)


class Tracer:
    def __init__(self, path: str | Path | None = None, keep: bool = True, stream=None):
        self.events: list[dict] = []
        self.keep = keep
        self.fh = open(path, "a", encoding="utf-8") if path else None
        self.stream = stream

    def emit(self, t: float, event: str, **fields) -> dict:
        rec = {"t": round(t, 3), "event": event, **fields}
        if "tokens_in" in fields:
            rec["cost_usd"] = cost_usd(fields.get("tokens_in", 0), fields.get("tokens_out", 0))
        if self.keep:
            self.events.append(rec)
        line = json.dumps(rec, ensure_ascii=False)
        if self.fh:
            self.fh.write(line + "\n")
            self.fh.flush()
        if self.stream:
            print(line, file=self.stream or sys.stdout, flush=True)
        return rec
