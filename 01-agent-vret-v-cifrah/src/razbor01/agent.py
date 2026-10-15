"""Цикл агента на Claude API: ручной цикл tool use, чтобы писать полную трассу и считать токены."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .tools import ToolBox

DEFAULT_MODEL = "claude-sonnet-5-5"
# $ за 1M токенов (вход, выход); источник — прайс Anthropic на 2026-10-06
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclass
class ToolCall:
    name: str
    input: dict
    output: str
    is_error: bool = False


@dataclass
class AgentRun:
    value: float | None
    unit: str = ""
    explanation: str = ""
    metric_id: str | None = None
    trace: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    stop: str = "final_answer"   # final_answer | bad_answer | max_turns | refusal | no_answer | error

    def cost_usd(self, model: str) -> float:
        pin, pout = PRICES[model]
        return self.input_tokens * pin / 1e6 + self.output_tokens * pout / 1e6


def run_agent(question: str, box: ToolBox, client, model: str = DEFAULT_MODEL,
              max_turns: int = 12, clock=time.perf_counter) -> AgentRun:
    messages: list[dict] = [{"role": "user", "content": question}]
    run = AgentRun(value=None)
    t0 = clock()
    try:
        for _ in range(max_turns):
            resp = client.messages.create(model=model, max_tokens=16000, system=box.system,
                                          tools=box.specs, output_config={"effort": "medium"},
                                          messages=messages)
            run.input_tokens += resp.usage.input_tokens
            run.output_tokens += resp.usage.output_tokens
            if resp.stop_reason == "refusal":
                run.stop = "refusal"
                return run
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                run.stop = "no_answer"
                run.explanation = " ".join(b.text for b in resp.content if b.type == "text")
                return run
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for u in uses:
                args = dict(u.input)
                if u.name == "final_answer":
                    run.trace.append(ToolCall("final_answer", args, ""))
                    try:
                        value = float(args["value"])
                    except (KeyError, TypeError, ValueError, OverflowError):
                        value = math.nan
                    if not math.isfinite(value):  # nan и inf — не ответ
                        run.stop = "bad_answer"
                        return run
                    run.value = value
                    run.unit = str(args.get("unit", ""))
                    run.explanation = str(args.get("explanation", ""))
                    run.metric_id = args.get("metric_id")
                    run.stop = "final_answer"
                    return run
                out, err = box.call(u.name, args)
                run.trace.append(ToolCall(u.name, args, out, err))
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": out, "is_error": err})
            messages.append({"role": "user", "content": results})
        run.stop = "max_turns"
        return run
    except Exception as e:  # сбой API: оставляем известную трассу и токены, ошибку видно в stop
        run.stop = f"error: {type(e).__name__}: {e}"
        return run
    finally:
        run.seconds = clock() - t0
