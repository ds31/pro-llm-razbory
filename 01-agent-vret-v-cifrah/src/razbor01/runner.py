"""Прогон eval: каждый вопрос × каждый вариант, сводка по вариантам и ловушкам."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from .agent import DEFAULT_MODEL, AgentRun, run_agent
from .golden import TRAPS, Question, expected_value, is_correct, scalar
from .metrics import Catalog
from .tools import make_toolbox

_PKG_ROOT = str(Path(__file__).resolve().parents[2])
_HOME_RX = re.compile(r"(?:/home|/Users)/[^/\s'\"]+|/root\b")
# путь вида /a/b: не после слова, скобки или «/», чтобы не задеть деление и URL
_ABS_PATH_RX = re.compile(r"(?<![\w)\]/:.])/(?:[\w.\-]+/)+[\w.\-]*")


def scrub(text: str) -> str:
    """Убрать из текста абсолютные пути и имя пользователя ОС (ошибки DuckDB их содержат)."""
    text = text.replace(_PKG_ROOT, ".")
    home = str(Path.home())
    if len(home) > 1:
        text = text.replace(home, "~")
    text = _HOME_RX.sub("~", text)
    return _ABS_PATH_RX.sub("<path>", text)  # любой другой абсолютный путь, например --root в /tmp


@dataclass
class QuestionResult:
    qid: str
    trap: str
    question: str
    variant: str
    expected: float
    got: float | None
    correct: bool
    cost_usd: float
    seconds: float
    stop: str
    run: AgentRun
    trap_value: float | None = None  # что получится в ловушке; для «none» — None


def _scrub_run(run: AgentRun) -> None:
    run.explanation = scrub(run.explanation)
    run.stop = scrub(run.stop)
    for c in run.trace:
        c.output = scrub(c.output)
        c.input = json.loads(scrub(json.dumps(c.input, ensure_ascii=False, default=str)))


def run_eval(con: duckdb.DuckDBPyConnection, catalog: Catalog, questions: list[Question], client,
             variants: tuple[str, ...] = ("A", "B"), model: str = DEFAULT_MODEL,
             on_result=None) -> list[QuestionResult]:
    results = []
    for variant in variants:
        box = make_toolbox(variant, con, catalog)
        for q in questions:
            exp = expected_value(con, q)
            trap_value = scalar(con, q.trap_sql) if q.trap_sql else None
            try:
                run = run_agent(q.question, box, client, model=model)
            except Exception as e:  # страховка: сбой на одном вопросе не роняет платный прогон
                run = AgentRun(value=None, stop=f"error: {type(e).__name__}: {e}")
            _scrub_run(run)
            r = QuestionResult(q.id, q.trap, q.question, variant, exp, run.value,
                               is_correct(run.value, exp), run.cost_usd(model), run.seconds, run.stop, run,
                               trap_value)
            results.append(r)
            if on_result:
                on_result(r)
    return results


def summarize(results: list[QuestionResult]) -> dict:
    out: dict = {}
    for v in sorted({r.variant for r in results}):
        rs = [r for r in results if r.variant == v]
        n = len(rs)
        out[v] = {
            "n": n,
            "errors": sum(r.stop.startswith("error") for r in rs),
            "correct": sum(r.correct for r in rs),
            "accuracy_pct": round(100 * sum(r.correct for r in rs) / n, 1),
            "cost_usd_per_q": round(sum(r.cost_usd for r in rs) / n, 4),
            "seconds_per_q": round(sum(r.seconds for r in rs) / n, 1),
            "by_trap": {t: f"{sum(r.correct for r in rs if r.trap == t)}/{sum(1 for r in rs if r.trap == t)}"
                        for t in TRAPS if any(r.trap == t for r in rs)},
        }
    return out


def append_jsonl(r: QuestionResult, path: Path | str) -> None:
    """Дописать один результат сразу: упавший или прерванный платный прогон не теряет сделанное."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(scrub(json.dumps(asdict(r), ensure_ascii=False)) + "\n")


def save_jsonl(results: list[QuestionResult], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(scrub(json.dumps(asdict(r), ensure_ascii=False)) + "\n")
    return path
