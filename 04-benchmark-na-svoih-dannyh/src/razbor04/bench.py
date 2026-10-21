"""Прогон eval пакета 01 на нескольких моделях и сводка: точность, цена, время, $ за верный ответ."""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field

import duckdb

from razbor01.agent import AgentRun, run_agent
from razbor01.golden import TRAPS, Question, expected_value, is_correct
from razbor01.metrics import Catalog
from razbor01.runner import _scrub_run
from razbor01.tools import make_toolbox

from .client import MeteredClient
from .prices import list_cost, order


@dataclass
class BenchResult:
    model: str
    variant: str
    run: int
    qid: str
    trap: str
    question: str
    expected: float
    got: float | None
    correct: bool
    stop: str                      # final_answer | bad_answer | max_turns | refusal | no_answer | error: …
    steps: int                     # вызовов модели в цикле агента
    tools: list[str]               # инструменты по порядку
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost_list_usd: float           # по прайсу (prices.py), весь вход — по полной цене
    cost_billed_usd: float | None  # списано OpenRouter (usage.cost); None — шлюз цену не вернул
    seconds: float
    explanation: str = ""
    cache_read_tokens: int = 0     # вход из кэша провайдера; в input_tokens не входит
    trace: list[dict] | None = field(default=None, repr=False)  # только в eval/out, не в reference-run.json

    @property
    def api_error(self) -> bool:
        return self.stop.startswith("error")


def run_bench(con: duckdb.DuckDBPyConnection, catalog: Catalog, questions: list[Question], make_client,
              models: list[str], variants: tuple[str, ...] = ("A", "B"), runs: tuple[int, ...] = (1,),
              effort: str | None = "medium", priced: bool = True, max_usd: float | None = None,
              on_result=None, max_turns: int = 12) -> list[BenchResult]:
    """Каждая модель × прогон × вариант × вопрос. max_usd — стоп-кран: новый вопрос не начинается,
    когда потрачено столько (по списанию OpenRouter, а если его нет — по прайсу)."""
    results: list[BenchResult] = []
    spent = 0.0
    boxes = {v: make_toolbox(v, con, catalog) for v in variants}
    expected = {q.id: expected_value(con, q) for q in questions}
    for model in models:
        client = MeteredClient(make_client(model), effort)
        for run in runs:
            for variant in variants:
                for q in questions:
                    if max_usd is not None and spent >= max_usd:
                        return results
                    client.take()
                    try:
                        ar = run_agent(q.question, boxes[variant], client, model=model, max_turns=max_turns)
                    except Exception as e:  # страховка: сбой одного вопроса не роняет платный прогон
                        ar = AgentRun(value=None, stop=f"error: {type(e).__name__}: {e}")
                    _scrub_run(ar)
                    calls = client.take()
                    tin = sum(c.input_tokens for c in calls)
                    tout = sum(c.output_tokens for c in calls)
                    billed = [c.billed_usd for c in calls]
                    cost_billed = sum(billed) if billed and all(b is not None for b in billed) else None
                    cache = sum(c.cache_read_tokens for c in calls)
                    # по прайсу — весь вход по полной цене входа: без кэша, скидок и наценок провайдера
                    cost_list = list_cost(model, tin + cache, tout) if priced else 0.0
                    spent += cost_billed if cost_billed is not None else cost_list
                    r = BenchResult(
                        model=model, variant=variant, run=run, qid=q.id, trap=q.trap, question=q.question,
                        expected=expected[q.id], got=ar.value, correct=is_correct(ar.value, expected[q.id]),
                        stop=ar.stop, steps=len(calls), tools=[c.name for c in ar.trace], input_tokens=tin,
                        output_tokens=tout, thinking_tokens=sum(c.thinking_tokens for c in calls),
                        cost_list_usd=cost_list, cost_billed_usd=cost_billed, seconds=ar.seconds,
                        explanation=ar.explanation[:400],
                        cache_read_tokens=cache, trace=[asdict(c) for c in ar.trace])
                    results.append(r)
                    if on_result:
                        on_result(r)
    return results


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def summarize(results: list[BenchResult]) -> dict:
    """{модель: {вариант: метрики}}. Несколько прогонов — среднее и счёт по каждому (разброс).

    Деньги (usd_per_answer, usd_per_correct) — по списанию шлюза, если оно известно для всех ответов,
    иначе по прайсу. Прайс отдельно — list_usd_per_answer."""
    out: dict = {}
    for model in sorted(dict.fromkeys(r.model for r in results), key=order):
        out[model] = {}
        for v in sorted({r.variant for r in results if r.model == model}):
            rs = [r for r in results if r.model == model and r.variant == v]
            runs = sorted({r.run for r in rs})
            correct_by_run = [sum(r.correct for r in rs if r.run == k) for k in runs]
            total_correct = sum(correct_by_run)
            billed = [r.cost_billed_usd for r in rs]
            list_cost_ = sum(r.cost_list_usd for r in rs)
            has_billed = all(b is not None for b in billed)
            cost = sum(billed) if has_billed else list_cost_   # деньги: списанное, а без него — прайс
            traps = [t for t in TRAPS if any(r.trap == t for r in rs)]
            out[model][v] = {
                "runs": len(runs),
                "n": len({r.qid for r in rs}),
                "correct": round(_mean(correct_by_run), 2),
                "correct_by_run": correct_by_run,
                "api_errors": sum(r.api_error for r in rs),
                "wrong": sum(not r.correct and not r.api_error for r in rs),
                "no_number": sum(r.got is None and not r.api_error for r in rs),
                "cost_source": "списано" if has_billed else "прайс",
                "usd_per_answer": round(cost / len(rs), 6),
                "list_usd_per_answer": round(list_cost_ / len(rs), 6),
                "billed_usd_per_answer": round(sum(billed) / len(rs), 6) if has_billed else None,
                "usd_per_correct": round(cost / total_correct, 6) if total_correct else None,
                "seconds_per_answer": round(_mean([r.seconds for r in rs]), 1),
                "seconds_median": round(statistics.median(r.seconds for r in rs), 1),
                "steps_per_answer": round(_mean([r.steps for r in rs]), 1),
                "input_tokens_per_answer": round(_mean([r.input_tokens for r in rs])),
                "output_tokens_per_answer": round(_mean([r.output_tokens for r in rs])),
                "thinking_tokens_per_answer": round(_mean([r.thinking_tokens for r in rs])),
                "cache_read_tokens_per_answer": round(_mean([r.cache_read_tokens for r in rs])),
                "by_trap": {t: [sum(r.correct for r in rs if r.run == k and r.trap == t) for k in runs]
                            for t in traps},
                "by_trap_n": {t: len({r.qid for r in rs if r.trap == t}) for t in traps},
            }
    return out
