"""Ответы агента для приёмки: записанный прогон пакета 01 и свои прогоны razbor01 (results.jsonl).

Ответ привязан к кейсу по варианту и дословному тексту вопроса: другой формулировке — другой ответ.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

Key = tuple[str, str]   # (вариант, текст вопроса)


@dataclass(frozen=True)
class Answer:
    value: float | None
    cost_usd: float
    seconds: float
    source: str                 # откуда ответ: reference-run 01, results.jsonl …
    expected: float | None = None


def load_recorded(pkg01: Path) -> dict[Key, Answer]:
    """Прогон автора пакета 01: eval/reference-run.json + тексты вопросов из eval/questions.yaml."""
    questions = yaml.safe_load((pkg01 / "eval" / "questions.yaml").read_text(encoding="utf-8"))
    text = {q["id"]: q["question"] for q in questions}
    run = json.loads((pkg01 / "eval" / "reference-run.json").read_text(encoding="utf-8"))
    src = f"пакет 01, eval/reference-run.json ({run['meta'].get('дата прогона', '')})"
    return {(a["variant"], text[a["qid"]]): Answer(a["got"], a["cost_usd"], a["seconds"], src, a["expected"])
            for a in run["answers"]}


def load_results_jsonl(path: Path | str) -> dict[Key, Answer]:
    """Свой прогон: eval/out/results.jsonl, который пишет `razbor01 eval --root <папка экспорта>`."""
    out: dict[Key, Answer] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out[(r["variant"], r["question"])] = Answer(r["got"], r["cost_usd"], r["seconds"], str(path), r["expected"])
    return out
