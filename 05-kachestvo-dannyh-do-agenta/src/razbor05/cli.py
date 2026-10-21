"""Запуск одной командой: uv run razbor05 all."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import duckdb

from .close import check_month
from .defects import DEFECTS
from .experiment import SHOWCASE, random_runs, run_showcase, summarize_random
from .feed import FEED_SEED, MONTH, build_base
from .gate import Gate
from .modes import SHORT
from .report import render_report
from .rules import load_rules

KEYS = ("raw", "rules01", "gate")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="razbor05", description="Качество данных до агента: правила, карантин, закрытие")
    p.add_argument("command", choices=["data", "rules", "showcase", "scenarios", "replay", "close", "agent", "all"])
    p.add_argument("--root", default=".", help="папка пакета (по умолчанию текущая)")
    p.add_argument("--defect", default="all", help=f"сценарий витрины: {', '.join(SHOWCASE)}")
    p.add_argument("--until", default="2026-11-06", help="replay: до какого утра (YYYY-MM-DD)")
    p.add_argument("--as-of", default="2026-11-03", help="close: утро, на которое проверить чек-лист октября")
    p.add_argument("-n", "--scenarios", type=int, default=200, help="число случайных сценариев")
    p.add_argument("--workers", type=int, default=0, help="процессов для сценариев (0 — по числу ядер)")
    p.add_argument("--reference", action="store_true",
                   help="записать результат прогона автора: eval/reference-run.json или eval/agent-run.json")
    p.add_argument("--model", default="anthropic/claude-sonnet-5.5", help="agent: модель агента B пакета 01")
    p.add_argument("--only", default="", help="agent: id вопросов через запятую, например Q19,N1")
    p.add_argument("--offline", action="store_true", help="agent: без API — эталонные запросы слоя метрик")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    base = root / "data" / "base.duckdb"
    if args.command == "rules":
        for r in load_rules():
            print(f"{r.id}  {r.severity:5} {r.action:4} fix={r.fix:6} {r.title}\n     {r.why}")
        return 0
    if args.command in ("data", "all") or not base.exists():
        build_base(base)
        print(f"история пакета 01: {base}")
    if args.command == "data":
        return 0
    if args.defect not in SHOWCASE:
        print(f"нет сценария {args.defect}; есть: {', '.join(SHOWCASE)}")
        return 2
    if args.command == "showcase":
        names = SHOWCASE if args.defect == "all" else [args.defect]
        for name in names:
            _print_showcase(name, asdict(run_showcase(base, name)))
        return 0
    if args.command == "scenarios":
        print(json.dumps(summarize_random(random_runs(base, args.scenarios, workers=args.workers)),
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == "replay":
        res = run_showcase(base, args.defect, timeline=True, keys=("gate",), until=date.fromisoformat(args.until))
        _print_replay(asdict(res))
        return 0
    if args.command == "close":
        as_of = date.fromisoformat(args.as_of)
        _print_close(base, args.defect, as_of)
        return 0
    if args.command == "agent":
        return _agent(root, base, args)
    # all
    ref = run_all(base, args.scenarios, args.workers)
    out = root / "eval" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.html").write_text(render_report(ref), encoding="utf-8")
    if args.reference:
        (root / "eval" / "reference-run.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")
    for name in SHOWCASE:
        _print_showcase(name, ref["showcase"][name])
    print(json.dumps(ref["random"]["summary"]["modes"], ensure_ascii=False, indent=1))
    print(f"отчёт: {out / 'report.html'}")
    return 0


def _agent(root: Path, base: Path, args) -> int:
    from razbor01.agent import PRICES

    from .agent_check import run, to_json
    if not args.offline and args.model not in PRICES:
        print(f"нет цены для модели {args.model}: добавьте её в PRICES пакета 01")
        return 2
    client = None
    if not args.offline:
        import anthropic
        client = anthropic.Anthropic()
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    answers, state = run(base, root / "data" / "gate-2026-11-03.duckdb", client, args.model, only)
    for a in answers:
        exp = "—" if a.expected is None else f"{a.expected:,.2f}".replace(",", " ")
        got = "—" if a.got is None else f"{a.got:,.2f}".replace(",", " ")
        print(f"{a.setup:8} {a.qid:4} {'OK ' if a.correct else 'ERR'} {got:>16} / {exp:>16}  ${a.cost_usd:.4f}  {a.stop}")
    data = to_json(answers, state, args.model, args.offline)
    print(json.dumps(data["summary"], ensure_ascii=False))
    out = root / "eval" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "agent.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.reference and not args.offline:
        (root / "eval" / "agent-run.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def run_all(base: Path, n: int, workers: int) -> dict:
    con = duckdb.connect()
    try:
        history = Gate(con, base).history
    finally:
        con.close()
    show = {}
    for name in SHOWCASE:
        res = asdict(run_showcase(base, name, timeline=(name == "all")))
        show[name] = res
    runs = random_runs(base, n, workers=workers)
    compact = [{"seed": r["seed"], "defects": [d["defect"] for d in r["detection"]],
                "caught": [d["caught_any"] for d in r["detection"]],
                **{k: {"close_day": r["modes"][k]["close_day"],
                       "error_pct": None if r["modes"][k]["error_pct"] is None else round(r["modes"][k]["error_pct"], 3),
                       "correct_at_close": r["modes"][k]["correct_at_close"],
                       "rewritten": r["modes"][k]["rewritten"]} for k in KEYS}} for r in runs]
    return {
        "meta": {"run_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "feed_seed": FEED_SEED,
                 "random_first_seed": 1000, "scenarios": n, "llm": "нет — ответы эталонными запросами слоя метрик 01",
                 "tolerance_pct": 0.5},
        "history": history,
        "showcase": show,
        "random": {"summary": summarize_random(runs), "scenarios": compact},
    }


def _print_showcase(name: str, r: dict) -> None:
    label = DEFECTS[name][0] if name in DEFECTS else name
    print(f"\n== {label}  (правда: выручка октября {r['truth_revenue']:,.2f} ₽)".replace(",", " "))
    for k in KEYS:
        m = r["modes"][k]
        err = "—" if m["error_pct"] is None else f"{m['error_pct']:+.2f} %"
        print(f"  {SHORT[k]:11} закрыт {m['close_day'] or 'нет':10}  ошибка {err:>9}  верных {m['correct_at_close']}/9"
              f"{'  переписан задним числом' if m['rewritten'] else ''}")
    for d in r["detection"]:
        print(f"  {d['defect']}: {'поймано ' + ','.join(d['rules']) if d['caught_any'] else 'НЕ поймано'}")


def _print_replay(r: dict) -> None:
    for row in r["timeline"]:
        g = row["gate"]
        if not (g["loads"] or g["violations"] or g["released"] or g["closures"] or g["missing"]):
            continue
        viol = ", ".join(f"{k}×{v}" for k, v in g["violations"].items())
        print(f"{row['day']}  файлов {g['loads']:3}  принято {g['accepted']:5}  карантин {g['held_total']:3}  "
              f"отпущено {g['released']:3}  {viol}")
        for x in g["requests"]:
            print(f"            запрос исправленного файла: {x}")
        if g["missing"]:
            print(f"            нет файла: {', '.join(g['missing'])}")
        for c in g["closures"]:
            print(f"            закрытие {c}")
    for line in r["gate_log"]["quarantine"]:
        print("карантин:", " · ".join(line))


def _print_close(base: Path, defect: str, as_of: date) -> None:
    def inspect(modes):
        con = modes["gate"].con
        gate = modes["gate"].gate
        print(f"утро {as_of:%d.%m.%Y}: closed_through = {gate.closed_through()}")
        if gate.closed_through() >= date(2026, 10, 31):
            print("октябрь уже закрыт:", con.execute("SELECT closed_on FROM core.closures WHERE month = ?",
                                                     [MONTH]).fetchone()[0])
            return
        for c in check_month(con, MONTH):
            print(f"  {c.id} {'да ' if c.ok else 'нет'}  {c.title}")
            for p in c.problems[:8]:
                print("        ", " · ".join(map(str, p)))
    run_showcase(base, defect, keys=("gate",), until=as_of, inspect=inspect)
