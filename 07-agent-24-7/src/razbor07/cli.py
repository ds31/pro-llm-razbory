"""Команда пакета 07. Прогон без живого LLM: uv run razbor07 all."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from .agent import CONFIGS
from .experiment import MAIN_SEED, PROFILES, run_all, run_profiles, trace_example
from .fakellm import Faults
from .report import NAMES, render_report
from .sim import simulate

ROWS = (("delivered", "доставлено"), ("lost", "потеряно"), ("dup_tasks", "дубли"), ("dead", "dead-letter"),
        ("p50", "p50, с"), ("p95", "p95, с"), ("trace_complete", "трасса до конца"),
        ("calls_per_delivered", "вызовов на ответ"), ("rejected_429", "отказов 429"), ("crashes", "kill -9"))


def _table(configs: dict) -> str:
    head = f"{'':18}" + "".join(f"{k:>12}" for k in configs)
    lines = [head]
    for key, label in ROWS:
        lines.append(f"{label:18}" + "".join(f"{str(m[key]):>12}" for m in configs.values()))
    return "\n".join(lines)


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _faults_from_env() -> Faults:
    f = Faults()
    return replace(f, rpm_limit=int(_env_float("FAULT_RPM_LIMIT", f.rpm_limit)),
                   p_overload=_env_float("FAULT_P_OVERLOAD", f.p_overload),
                   p_hang=_env_float("FAULT_P_HANG", f.p_hang),
                   p_drop=_env_float("FAULT_P_DROP", f.p_drop),
                   p_poison=_env_float("FAULT_P_POISON", f.p_poison))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="razbor07", description="Агент 24/7: очередь, ретраи, идемпотентность, трассы")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("all", help="ночь, сбои по одному, N ночей, трасса, отчёт")
    a.add_argument("-n", "--nights", type=int, default=100)
    a.add_argument("--workers", type=int, default=0, help="процессов (0 — по числу ядер)")
    a.add_argument("--reference", action="store_true", help="записать eval/reference-run.json")
    a.add_argument("--root", default=".")
    s = sub.add_parser("night", help="одна ночь в одной или всех конфигурациях")
    s.add_argument("--config", choices=["all", *CONFIGS], default="all")
    s.add_argument("--profile", choices=list(PROFILES), default="all")
    s.add_argument("--seed", type=int, default=MAIN_SEED)
    f = sub.add_parser("faults", help="сбои по одному: потеряно, дубли, p95")
    f.add_argument("--seed", type=int, default=MAIN_SEED)
    t = sub.add_parser("trace", help="трасса одной задачи (JSON Lines)")
    t.add_argument("--config", choices=list(CONFIGS), default="prod")
    t.add_argument("--task", default="", help="ключ задачи; по умолчанию — пример из отчёта")
    t.add_argument("--seed", type=int, default=MAIN_SEED)
    api = sub.add_parser("api", help="HTTP API: POST /tasks → очередь")
    api.add_argument("--db", default=os.environ.get("QUEUE_DB", "data/queue.db"))
    api.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    w = sub.add_parser("worker", help="воркер агента")
    w.add_argument("--db", default=os.environ.get("QUEUE_DB", "data/queue.db"))
    w.add_argument("--name", default=os.environ.get("WORKER_NAME", os.environ.get("HOSTNAME", "w")))
    w.add_argument("--exit-when-idle", action="store_true")
    ld = sub.add_parser("load", help="отправить N вопросов в API")
    ld.add_argument("--url", default="http://localhost:8080")
    ld.add_argument("-n", type=int, default=200)
    ld.add_argument("--resend-share", type=float, default=0.1)
    ld.add_argument("--prefix", default="live")
    c = sub.add_parser("check", help="итог по базе очереди: статусы, dead-letter, дубли писем")
    c.add_argument("--db", default=os.environ.get("QUEUE_DB", "data/queue.db"))
    c.add_argument("--wait", type=float, default=0.0, help="ждать, пока очередь опустеет, секунд")
    h = sub.add_parser("health", help="healthcheck воркера: файл жизни свежее N секунд")
    h.add_argument("--file", default="/tmp/worker.alive")
    h.add_argument("--max-age", type=float, default=30.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "all":
        root = Path(args.root).resolve()
        ref = run_all(args.nights, args.workers)
        out = root / "eval" / "out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "run.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "report.html").write_text(render_report(ref), encoding="utf-8")
        if args.reference:
            (root / "eval" / "reference-run.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")
        print(f"Ночь по умолчанию, seed {ref['meta']['main_seed']}:")
        print(_table(ref["main"]))
        s = ref["nights"]["summary"]
        print(f"\n{ref['nights']['n']} ночей: ночей с потерями — " +
              ", ".join(f"{NAMES[k]} {s[k]['nights_with_lost']}" for k in s) +
              "; с дублями — " + ", ".join(f"{NAMES[k]} {s[k]['nights_with_dup']}" for k in s))
        print(f"\nОтчёт: {out / 'report.html'}")
        return 0
    if args.command == "night":
        night = PROFILES[args.profile][1]
        names = list(CONFIGS) if args.config == "all" else [args.config]
        print(f"{PROFILES[args.profile][0]}, seed {args.seed}")
        print(_table({k: simulate(CONFIGS[k], night, args.seed).metrics for k in names}))
        return 0
    if args.command == "faults":
        for p in run_profiles(args.seed).values():
            cells = "   ".join(f"{k}: потеряно {m['lost']}, дубли {m['dup_tasks']}, p95 {m['p95']} с"
                               for k, m in p["configs"].items())
            print(f"{p['title']}\n  {cells}")
        return 0
    if args.command == "trace":
        if args.task:
            res = simulate(CONFIGS[args.config], PROFILES["all"][1], args.seed)
            events = [e for e in res.events if e.get("task") == args.task]
        else:
            events = trace_example(args.seed)["configs"][args.config]
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        return 0 if events else 1
    if args.command in ("api", "worker"):
        from .trace import Tracer
        from .worker import Clock, Worker
        clock = Clock(_env_float("TIME_SCALE", 1.0))
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        tracer = Tracer(os.environ.get("TRACE_FILE") or None, keep=False, stream=sys.stdout)
        if args.command == "api":
            from .api import make_server
            srv = make_server(args.db, port=args.port, clock=clock, tracer=tracer)
            tracer.emit(clock.now(), "api_started", port=args.port)
            srv.serve_forever()
            return 0
        Worker(args.db, args.name, faults=_faults_from_env(), seed=int(_env_float("SEED", MAIN_SEED)), clock=clock,
               tracer=tracer, alive_file=os.environ.get("ALIVE_FILE", "/tmp/worker.alive"),
               chaos_kill_p=_env_float("CHAOS_KILL_P", 0.0)).run(exit_when_idle=args.exit_when_idle)
        return 0
    if args.command == "load":
        from .load import run_load
        print(json.dumps(run_load(args.url, args.n, args.resend_share, prefix=args.prefix), ensure_ascii=False))
        return 0
    if args.command == "check":
        from .load import check
        out = check(args.db, wait=args.wait)
        out["dead_letter"] = [{k: d[k] for k in ("key", "attempts", "last_error")} for d in out["dead_letter"]]
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if out["duplicate_mail"] == 0 else 1
    if args.command == "health":
        import time
        try:
            age = time.time() - os.path.getmtime(args.file)
        except OSError:
            return 1
        return 0 if age <= args.max_age else 1
    return 2
