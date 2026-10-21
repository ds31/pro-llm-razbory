"""Запуск одной командой: uv run razbor04 all."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from razbor01.golden import load_questions
from razbor01.layers import prepare_db
from razbor01.metrics import load_catalog
from razbor01.tools import open_db

from .bench import run_bench, summarize
from .paths import BASE
from .prices import DEFAULT_MODELS, PRICES, UnknownModel, order, price, slug
from .reference import append_jsonl, from_reference, load_jsonl, to_reference

PRICE_SOURCE = "прайс OpenRouter на 2026-10-21"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="razbor04", description="Бенчмарк моделей на eval агента-аналитика (пакет 01)")
    p.add_argument("command", choices=["data", "bench", "report", "all", "models"])
    p.add_argument("--root", default=".", help="папка пакета (по умолчанию текущая)")
    p.add_argument("--base", default=str(BASE), help="папка пакета 01: eval/questions.yaml и metrics.yaml")
    p.add_argument("--models", default=",".join(DEFAULT_MODELS), help="модели через запятую")
    p.add_argument("--variants", default="A,B")
    p.add_argument("--only", default="", help="id вопросов через запятую, например Q07,Q19")
    p.add_argument("--limit", type=int, default=0, help="первые N вопросов")
    p.add_argument("--run", type=int, default=1, help="номер прогона (для второго прогона — 2)")
    p.add_argument("--repeat", type=int, default=1, help="сколько прогонов подряд, начиная с --run")
    p.add_argument("--effort", default="medium", help="output_config.effort для всех моделей; none — не слать")
    p.add_argument("--max-usd", type=float, default=None, help="стоп-кран: не начинать новый вопрос после этой суммы")
    p.add_argument("--offline", action="store_true", help="без API: эталонные ответы, проверка конвейера")
    p.add_argument("--from", dest="src", default="", help="report: собрать отчёт из reference-run.json")
    p.add_argument("--write-reference", action="store_true", help="report: записать eval/reference-run.json")
    return p


def _client(offline: bool, con, questions):
    if offline:
        from razbor01.offline import OracleClient
        return lambda model: OracleClient(con, questions)
    import anthropic
    if os.environ.get("OPENROUTER_API_KEY") and not os.environ.get("ANTHROPIC_BASE_URL"):
        base, token = "https://openrouter.ai/api", os.environ["OPENROUTER_API_KEY"]
        return lambda model: anthropic.Anthropic(base_url=base, auth_token=token, api_key=None)
    return lambda model: anthropic.Anthropic()


def _report(out: Path, results, meta) -> dict:
    from .report import render_report
    summary = summarize(results)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    (out / "report.html").write_text(render_report(results, summary, meta), encoding="utf-8")
    return summary


def _print_summary(summary: dict) -> None:
    for m, vs in summary.items():
        for v, s in vs.items():
            pc = "—" if s["usd_per_correct"] is None else f'{s["usd_per_correct"]:.4f}'
            print(f'{m:32} {v}  верно {s["correct"]:g}/{s["n"]} {s["correct_by_run"]}  API {s["api_errors"]}  '
                  f'${s["usd_per_answer"]:.4f}/ответ  ${pc}/верный  {s["seconds_per_answer"]} с')


def _meta(results, args, offline: bool) -> dict:
    models = sorted(dict.fromkeys(r.model for r in results), key=order)
    runs = {m: len({r.run for r in results if r.model == m}) for m in models}
    return {"модели": ", ".join(f"{m} ×{runs[m]}" for m in models), "вопросов": len({r.qid for r in results}),
            "effort": args.effort,
            "цены": "офлайн-эталон, без цены" if offline else PRICE_SOURCE,
            "дата прогона": datetime.now().strftime("%Y-%m-%d %H:%M")}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    out = root / "eval" / "out"
    if args.command == "models":
        for m, (pin, pout) in PRICES.items():
            print(f"{m:32} вход ${pin:g} / выход ${pout:g} за 1M токенов")
        print(f"источник: {PRICE_SOURCE}")
        return 0
    if args.command == "report":
        if args.src:
            results, meta = from_reference(args.src)
        else:
            results = load_jsonl(sorted((out / "runs").glob("*.jsonl")))
            if not results:
                print(f"нет прогонов в {out / 'runs'}: сначала razbor04 bench")
                return 2
            meta = _meta(results, args, all(r.cost_list_usd == 0 for r in results))
        summary = _report(out, results, meta)
        if args.write_reference:
            ref = root / "eval" / "reference-run.json"
            ref.write_text(json.dumps(to_reference(results, summary, meta), ensure_ascii=False, indent=1),
                           encoding="utf-8")
            print(f"прогон автора: {ref}")
        _print_summary(summary)
        print(f"отчёт: {out / 'report.html'}")
        return 0

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not args.offline:
        try:
            for m in models:
                price(m)
        except UnknownModel as e:
            print(e)
            return 2
    base = Path(args.base).resolve()
    questions = load_questions(base / "eval" / "questions.yaml")
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        unknown = wanted - {q.id for q in questions}
        if unknown:
            print(f"нет вопросов: {', '.join(sorted(unknown))}")
            return 2
        questions = [q for q in questions if q.id in wanted]
    if args.limit:
        questions = questions[: args.limit]
    db = root / "data" / "retail.duckdb"
    if args.command in ("data", "all") or not db.exists():
        prepare_db(db)
        print(f"данные: {db}")
    if args.command == "data":
        return 0

    runs = tuple(range(args.run, args.run + args.repeat))
    variants = tuple(v.strip() for v in args.variants.split(",") if v.strip())
    for m in models:
        for k in runs:
            (out / "runs" / f"{slug(m)}.r{k}.jsonl").unlink(missing_ok=True)

    def on_result(r):
        append_jsonl(r, out / "runs" / f"{slug(r.model)}.r{r.run}.jsonl")
        billed = "—" if r.cost_billed_usd is None else f"{r.cost_billed_usd:.4f}"
        print(f"{r.model} r{r.run} {r.qid} {r.variant} {'OK ' if r.correct else 'ERR'} {r.got} / {r.expected:.2f}  "
              f"{r.seconds:.1f}s  ${r.cost_list_usd:.4f} (списано {billed})  {r.stop[:80]}", flush=True)

    con = open_db(db)  # только чтение и без внешнего доступа
    try:
        results = run_bench(con, load_catalog(base / "metrics.yaml"), questions, _client(args.offline, con, questions),
                            models=models, variants=variants, runs=runs,
                            effort=None if args.effort.lower() == "none" else args.effort,
                            priced=not args.offline, max_usd=args.max_usd, on_result=on_result)
    finally:
        con.close()
    total = sum((r.cost_billed_usd if r.cost_billed_usd is not None else r.cost_list_usd) for r in results)
    print(f"ответов: {len(results)}, потрачено: ${total:.4f}")
    # отчёт — по всем прогонам в eval/out/runs, в том числе сделанным раньше другими командами
    all_results = load_jsonl(sorted((out / "runs").glob("*.jsonl")))
    summary = _report(out, all_results, _meta(all_results, args, args.offline))
    _print_summary(summary)
    print(f"отчёт: {out / 'report.html'}")
    return 0
