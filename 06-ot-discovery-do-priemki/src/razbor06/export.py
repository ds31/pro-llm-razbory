"""Экспорт вопросов, которые ждут прогона, в формат пакета 01: `uv run razbor01 eval --root <папка>` прогонит агента."""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from .accept import Waiting
from .paths import PKG01


def export_agent_root(waiting: list[Waiting], out_dir: Path | str, db: Path | str | None = None) -> Path:
    """Папка для razbor01: eval/questions.yaml (вопросы без ответа), metrics.yaml пакета 01, база."""
    root = Path(out_dir)
    (root / "eval").mkdir(parents=True, exist_ok=True)
    items = []
    for n, w in enumerate(waiting, 1):
        item = {"id": f"{w.case_id}.{n:02d}", "trap": "none", "question": w.question, "check_sql": w.golden_sql}
        if w.metric_query:
            item["metric_query"] = w.metric_query
        items.append(item)
    (root / "eval" / "questions.yaml").write_text(
        "# Вопросы приёмки без ответа агента — экспорт razbor06. Прогон: uv run razbor01 eval --root <эта папка>\n"
        + yaml.safe_dump(items, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    shutil.copyfile(PKG01 / "metrics.yaml", root / "metrics.yaml")
    if db is not None:
        (root / "data").mkdir(exist_ok=True)
        shutil.copyfile(db, root / "data" / "retail.duckdb")
    return root
