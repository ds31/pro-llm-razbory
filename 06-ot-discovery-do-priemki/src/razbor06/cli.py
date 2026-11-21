"""Запуск одной командой: uv run razbor06 all.

check    — discovery готов к приёмке или чего не хватает;
scaffold — каркас кейсов приёмки из discovery;
accept   — ворота G1–G5 по вариантам прототипа, экспорт вопросов без ответа для razbor01;
all      — всё на сквозном примере: discovery после первой встречи и после недели, кейсы, ворота A и B.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import duckdb
import yaml
from razbor01.layers import prepare_db
from razbor01.metrics import load_catalog

from .accept import evaluate
from .answers import load_recorded, load_results_jsonl
from .discovery import check, load_discovery
from .export import export_agent_root
from .paths import EXAMPLE, PKG01, ROOT
from .profile import profile
from .report import check_json, check_text, markdown, plural, verdict_json
from .scaffold import dump_acceptance, scaffold


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="razbor06", description="Путь FDE: discovery → прототип → приёмка по eval")
    p.add_argument("command", choices=["check", "scaffold", "accept", "all"])
    p.add_argument("discovery", nargs="?", default=str(EXAMPLE / "discovery.yaml"))
    p.add_argument("-o", "--output", help="scaffold: куда записать кейсы (по умолчанию eval/out/acceptance.yaml)")
    p.add_argument("--prototype", default=str(EXAMPLE / "prototype.yaml"), help="спека прототипа с порогами")
    p.add_argument("--variants", default="A,B")
    p.add_argument("--results", action="append", default=[], help="results.jsonl своего прогона razbor01")
    p.add_argument("--no-catalog", action="store_true", help="не сверять метрики с каталогом пакета 01")
    p.add_argument("--out", default=str(ROOT / "eval" / "out"))
    p.add_argument("--db", default=str(ROOT / "data" / "retail.duckdb"))
    return p


def _rel(p: Path | str) -> str:
    """Путь для вывода: относительно текущей папки, если внутри неё."""
    try:
        return os.path.relpath(p)
    except ValueError:
        return str(p)


def _catalog_ids(args) -> set[str] | None:
    return None if args.no_catalog else set(load_catalog(PKG01 / "metrics.yaml").metrics)


def _accept(args, out: Path) -> tuple:
    proto = yaml.safe_load(Path(args.prototype).read_text(encoding="utf-8"))
    disc_path = Path(args.prototype).parent / proto["discovery"]
    d = load_discovery(disc_path)
    cases = scaffold(d)
    db = Path(args.db)
    if not db.exists():
        prepare_db(db)
        print(f"данные: база пакета 01 → {_rel(db)}")
    answers = load_recorded(PKG01)
    for r in args.results:
        answers.update(load_results_jsonl(r))
    catalog = load_catalog(PKG01 / "metrics.yaml")
    verdicts = {}
    con = duckdb.connect(str(db), read_only=True)
    try:
        prof = profile(con)
        for name in [v.strip() for v in args.variants.split(",") if v.strip()]:
            spec = proto["variants"][name]
            verdicts[name] = evaluate(con, catalog, cases, answers, name, layer=bool(spec.get("layer")),
                                      works_when=proto["works_when"])
    finally:
        con.close()
    for name, v in verdicts.items():
        if v.waiting:
            export_agent_root(v.waiting, out / f"agent-root-{name}", db)
    return proto, d, cases, verdicts, {n: s.get("title", "") for n, s in proto["variants"].items()}, prof


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    out = Path(args.out)

    if args.command == "check":
        rep = check(load_discovery(args.discovery), _catalog_ids(args))
        print(check_text(rep, Path(args.discovery).name))
        return 0 if rep.ready else 1

    if args.command == "scaffold":
        d = load_discovery(args.discovery)
        cases = scaffold(d)
        target = Path(args.output) if args.output else out / "acceptance.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dump_acceptance(cases, d), encoding="utf-8")
        todo = sum(1 for c in cases if c.todo)
        print(f"{len(cases)} {plural(len(cases), 'кейс', 'кейса', 'кейсов')}, из них с TODO: {todo} → {_rel(target)}")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    day1 = None
    if args.command == "all":
        day1 = check(load_discovery(EXAMPLE / "discovery-day1.yaml"), _catalog_ids(args))
        print(check_text(day1, "discovery-day1.yaml"), end="\n\n")
    proto, d, cases, verdicts, titles, prof = _accept(args, out)
    filled = check(d, _catalog_ids(args))
    print(check_text(filled, proto["discovery"]), end="\n\n")
    (out / "acceptance.yaml").write_text(dump_acceptance(cases, d), encoding="utf-8")
    ref01 = json.loads((PKG01 / "eval" / "reference-run.json").read_text(encoding="utf-8"))["meta"]
    summary = {
        "meta": {"дата прогона": datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "ответы агента": f"пакет 01, eval/reference-run.json: {ref01['модель']}, {ref01['дата прогона']}"
                                  + (f"; свои прогоны: {len(args.results)}" if args.results else ""),
                 "пороги": proto["works_when"]},
        "discovery": ({"day1": check_json(day1)} if day1 else {}) | {"filled": check_json(filled)},
        "acceptance": {"cases": len(cases),
                       "by_question": {q: sum(1 for c in cases if c.from_q == q) for q in dict.fromkeys(c.from_q for c in cases)},
                       "table_rows": sum(len(r.expected) for r in next(iter(verdicts.values())).cases
                                         if r.kind == "table" and isinstance(r.expected, dict)) if verdicts else 0,
                       "todo": sum(1 for c in cases if c.todo)},
        "variants": {n: verdict_json(v) for n, v in verdicts.items()},
        "profile": prof,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(markdown(d.get("project", ""), day1, filled, cases, verdicts, titles), encoding="utf-8")
    for n, v in verdicts.items():
        gates = " · ".join(f"{g} {x.status}" for g, x in v.gates.items())
        extra = f"; ждут прогона: {len(v.waiting)} → {_rel(out / f'agent-root-{n}')}" if v.waiting else ""
        print(f"{n}: {v.verdict} ({gates}){extra}")
    print(f"отчёт: {_rel(out / 'report.md')}")
    if args.command == "accept":
        return 0 if all(v.verdict == "принят" for v in verdicts.values()) else 1
    return 0
