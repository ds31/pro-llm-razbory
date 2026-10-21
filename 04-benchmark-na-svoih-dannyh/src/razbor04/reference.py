"""eval/reference-run.json: прогон автора — мета, сводка и все ответы (без трасс)."""
from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from razbor01.runner import scrub

from .bench import BenchResult


def to_reference(results: list[BenchResult], summary: dict, meta: dict) -> dict:
    answers = []
    for r in results:
        d = asdict(r)
        d.pop("trace")
        answers.append(d)
    return json.loads(scrub(json.dumps({"meta": meta, "summary": summary, "answers": answers}, ensure_ascii=False)))


def from_reference(path: Path | str) -> tuple[list[BenchResult], dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    names = {f.name for f in fields(BenchResult)}
    return [BenchResult(**{k: v for k, v in a.items() if k in names}) for a in data["answers"]], data["meta"]


def load_jsonl(paths) -> list[BenchResult]:
    names = {f.name for f in fields(BenchResult)}
    out = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:  # строка, которую параллельный прогон ещё дописывает
                continue
            out.append(BenchResult(**{k: v for k, v in d.items() if k in names}))
    return out


def append_jsonl(r: BenchResult, path: Path | str) -> None:
    """Дописать один ответ сразу: прерванный платный прогон не теряет сделанное."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(scrub(json.dumps(asdict(r), ensure_ascii=False, default=str)) + "\n")
