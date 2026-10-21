"""Прогон агента по набору вопросов. Прогон хранит только ответы; верно или нет — решает проверяющий.

Формат прогона (JSON): {"name", "meta": {...}, "answers": [{qid, value, unit, explanation, trace, ...}]}.
Ответ и вердикт разделены: один и тот же прогон можно проверить живым эталоном, замороженным
и судьёй-LLM — и сравнить проверяющих между собой.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from razbor01.runner import scrub

from .spec import Suite

TRACE_OUTPUT_MAX = 2000   # символов вывода инструмента в трассе: хватает судье и разбору, файл не пухнет


@dataclass
class Answer:
    qid: str
    value: float | None
    unit: str = ""
    explanation: str = ""
    trace: list[dict] = field(default_factory=list)   # [{name, input, output, is_error}]
    cost_usd: float = 0.0
    seconds: float = 0.0
    stop: str = "final_answer"


@dataclass
class Run:
    name: str
    meta: dict
    answers: list[Answer]

    def by_qid(self) -> dict[str, Answer]:
        return {a.qid: a for a in self.answers}

    def to_dict(self) -> dict:
        return {"name": self.name, "meta": self.meta, "answers": [asdict(a) for a in self.answers]}

    @classmethod
    def from_dict(cls, d: dict) -> "Run":
        return cls(d["name"], dict(d["meta"]), [Answer(**a) for a in d["answers"]])


class Agent(Protocol):
    """Всё, что каркас требует от агента: вопрос текстом → число с пояснением."""

    def answer(self, question: str) -> Answer: ...


def clip_trace(trace: list[dict], limit: int = TRACE_OUTPUT_MAX) -> list[dict]:
    out = []
    for c in trace:
        text = scrub(str(c.get("output", "")))
        if len(text) > limit:
            text = text[:limit] + f" …[обрезано, всего {len(text)} символов]"
        inp = json.loads(scrub(json.dumps(c.get("input", {}), ensure_ascii=False, default=str)))
        out.append({"name": c["name"], "input": inp, "output": text, "is_error": bool(c.get("is_error", False))})
    return out


def run_suite(agent: Agent, suite: Suite, name: str, meta: dict, only: set[str] | None = None,
              on_answer: Callable[[Answer], None] | None = None) -> Run:
    answers = []
    for q in suite.questions:
        if only and q.id not in only:
            continue
        try:
            a = agent.answer(q.question)
        except Exception as e:  # сбой на одном вопросе не роняет платный прогон
            a = Answer(qid=q.id, value=None, stop=f"error: {type(e).__name__}: {e}")
        a.qid = q.id
        a.explanation = scrub(a.explanation)
        a.stop = scrub(a.stop)
        a.trace = clip_trace(a.trace)
        answers.append(a)
        if on_answer:
            on_answer(a)
    meta = {**meta, "date": meta.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M"), "questions": len(answers)}
    return Run(name, meta, answers)


def save_run(run: Run, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_run(path: Path | str) -> Run:
    return Run.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
