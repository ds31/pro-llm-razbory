"""Запуск одной командой: uv run razbor01 all."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .agent import DEFAULT_MODEL, PRICES
from .golden import load_questions
from .layers import prepare_db
from .metrics import load_catalog
from .report import render_report
from .runner import append_jsonl, run_eval, save_jsonl, summarize
from .tools import open_db


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="razbor01", description="Агент на сырых таблицах (A) и на слое метрик (B)")
    p.add_argument("command", choices=["data", "eval", "all"])
    p.add_argument("--root", default=".", help="папка пакета (по умолчанию текущая)")
    p.add_argument("--variants", default="A,B")
    p.add_argument("--only", default="", help="id вопросов через запятую, например Q07,Q19")
    p.add_argument("--limit", type=int, default=0, help="первые N вопросов")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--offline", action="store_true", help="без API: эталонные ответы, проверка конвейера")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.offline and args.model not in PRICES:
        print(f"нет цены для модели {args.model}: добавьте её в PRICES (src/razbor01/agent.py)")
        return 2
    root = Path(args.root).resolve()
    db = root / "data" / "retail.duckdb"
    if args.command in ("data", "all") or not db.exists():
        prepare_db(db)
        print(f"данные: {db}")
    if args.command == "data":
        return 0
    questions = load_questions(root / "eval" / "questions.yaml")
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        unknown = wanted - {q.id for q in questions}
        if unknown:
            print(f"нет вопросов: {', '.join(sorted(unknown))}")
            return 2
        questions = [q for q in questions if q.id in wanted]
    if args.limit:
        questions = questions[: args.limit]
    model = DEFAULT_MODEL if args.offline else args.model  # офлайн токенов нет, цена нужна только для формы
    catalog = load_catalog(root / "metrics.yaml")
    out = root / "eval" / "out"
    (out / "results.jsonl").unlink(missing_ok=True)
    con = open_db(db)  # только чтение и без внешнего доступа
    try:
        if args.offline:
            from .offline import OracleClient
            client = OracleClient(con, questions)
        else:
            import anthropic
            client = anthropic.Anthropic()
        variants = tuple(v.strip() for v in args.variants.split(",") if v.strip())
        results = run_eval(con, catalog, questions, client, variants=variants, model=model,
                           on_result=lambda r: (append_jsonl(r, out / "results.jsonl"), print(f"{r.qid} {r.variant} {'OK ' if r.correct else 'ERR'} "
                                                     f"{r.got} / {r.expected:.2f}  {r.seconds:.1f}s  {r.stop}")))
    finally:
        con.close()
    summary = summarize(results)
    meta = {"модель": "офлайн-эталон" if args.offline else args.model, "вопросов": len(questions),
            "дата прогона": datetime.now().strftime("%Y-%m-%d %H:%M")}
    save_jsonl(results, out / "results.jsonl")
    (out / "summary.json").write_text(json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    (out / "report.html").write_text(render_report(results, summary, meta), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"отчёт: {out / 'report.html'}")
    return 0
