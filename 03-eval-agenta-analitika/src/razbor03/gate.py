"""Устойчивость на повторах и ворота: сравнение прогонов до и после правки.

Вход — вердикты живого эталона: список {qid: верно?} на каждый повтор.
pass@1 — средняя доля верных за один прогон; pass^k — доля вопросов, верных во всех k повторах
(мера надёжности из τ-bench); плавающие — верные не во всех повторах.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def _rates(runs: list[dict[str, bool]]) -> dict[str, float]:
    qids = sorted(set().union(*runs)) if runs else []
    return {q: sum(r[q] for r in runs if q in r) / sum(q in r for r in runs) for q in qids}


def stability(runs: list[dict[str, bool]]) -> dict:
    if not runs:
        raise ValueError("нужен хотя бы один прогон")
    common = sorted(set.intersection(*(set(r) for r in runs)))
    k = len(runs)
    rates = {q: sum(r[q] for r in runs) / k for q in common}
    return {
        "k": k,
        "questions": len(common),
        "pass_at_1": round(sum(rates.values()) / len(common), 4) if common else 0.0,
        "pass_hat_k": round(sum(v == 1 for v in rates.values()) / len(common), 4) if common else 0.0,
        "per_run": [sum(r[q] for q in common) for r in runs],
        "always": sorted(q for q, v in rates.items() if v == 1),
        "never": sorted(q for q, v in rates.items() if v == 0),
        "flaky": sorted(q for q, v in rates.items() if 0 < v < 1),
    }


@dataclass
class GateResult:
    questions: list[str]
    regressions: list[str]          # был верен во всех старых повторах, в новых — нет
    fixed: list[str]                # был неверен во всех старых, в новых верен всегда
    flaky_before: list[str]         # плавал до правки — не блокирует, но в отчёте виден
    old_correct: float
    new_correct: float
    allow: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.regressions) <= self.allow

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1


def compare(old: list[dict[str, bool]], new: list[dict[str, bool]], allow: int = 0) -> GateResult:
    """Ворота перед правкой промпта, модели или слоя данных. Сравниваются только общие вопросы."""
    ro, rn = _rates(old), _rates(new)
    common = sorted(set(ro) & set(rn))
    if not common:
        raise ValueError("у прогонов нет общих вопросов")
    return GateResult(
        questions=common,
        regressions=[q for q in common if ro[q] == 1 and rn[q] < 1],
        fixed=[q for q in common if ro[q] == 0 and rn[q] == 1],
        flaky_before=[q for q in common if 0 < ro[q] < 1],
        old_correct=round(sum(ro[q] for q in common), 2),
        new_correct=round(sum(rn[q] for q in common), 2),
        allow=allow,
    )
