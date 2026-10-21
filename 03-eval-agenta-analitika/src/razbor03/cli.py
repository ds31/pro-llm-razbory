"""Команды каркаса eval. Запуск одной командой: uv run razbor03 all --offline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import PRICES, load_factory
from .checkers import agreement, check_frozen, check_judge, check_live, freeze, verdicts_to_dict
from .experiment import JUDGES, MODEL, execute, import_01, load_store, save_store, summarize
from .gate import compare, stability
from .reference import expected, scalar, trap_bites
from .report import render
from .runs import Run, load_run, run_suite, save_run
from .scenarios import SCENARIOS, build_data, open_scenario
from .spec import load_suite

REF = Path("eval") / "reference-run.json"


def _p() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="razbor03", description="Каркас eval агента-аналитика: живые эталоны, повторы, ворота")
    p.add_argument("--root", default=".", help="папка пакета (по умолчанию текущая)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data", help="собрать базы сценариев в data/")
    s = sub.add_parser("refs", help="живые эталоны и проверка «ловушка кусает»")
    s.add_argument("--scenario", default="base", choices=sorted(SCENARIOS))
    s = sub.add_parser("freeze", help="записать эталонные числа на сегодняшние данные (для сравнения)")
    s.add_argument("--scenario", default="base", choices=sorted(SCENARIOS))
    s.add_argument("--out", default="eval/out/frozen.json")
    s = sub.add_parser("run", help="прогнать агента (платно)")
    s.add_argument("--scenario", default="base", choices=sorted(SCENARIOS))
    s.add_argument("--variant", default="B")
    s.add_argument("--only", default="", help="id через запятую")
    s.add_argument("--tag", default="", help="только вопросы с тегом")
    s.add_argument("--repeats", type=int, default=1)
    s.add_argument("--model", default=MODEL)
    s.add_argument("--agent", default="razbor03.agent:make", help="фабрика агента 'модуль:функция'")
    s.add_argument("--name", default="")
    s = sub.add_parser("check", help="проверить прогон живым или замороженным эталоном")
    s.add_argument("run")
    s.add_argument("--by", default="live", choices=["live", "frozen"])
    s.add_argument("--frozen", default="eval/out/frozen.json")
    s = sub.add_parser("judge", help="проверить прогон судьёй-LLM без эталона (платно) и сравнить с живым")
    s.add_argument("run")
    s.add_argument("--model", default="anthropic/claude-haiku-5.5")
    s = sub.add_parser("stability", help="pass@1, pass^k и плавающие вопросы по повторам")
    s.add_argument("runs", nargs="+")
    s = sub.add_parser("compare", help="ворота: код выхода 1, если правка сломала верные ответы")
    s.add_argument("--old", nargs="+", required=True)
    s.add_argument("--new", nargs="+", required=True)
    s.add_argument("--allow", type=int, default=0, help="сколько регрессий допустимо")
    s = sub.add_parser("all", help="весь эксперимент: офлайн — по прогону автора, иначе — платный прогон")
    s.add_argument("--offline", action="store_true")
    s.add_argument("--model", default=MODEL)
    s.add_argument("--max-usd", type=float, default=None, help="стоп по бюджету")
    s = sub.add_parser("import-01", help="ответы пакета 01 (eval/out/results.jsonl) → прогоны base-A-1 и base-B-1")
    s.add_argument("results")
    s.add_argument("--store", default="eval/out/experiment.json")
    return p


def _data(root: Path) -> Path:
    d = root / "data"
    if not all((d / sc.db).exists() for sc in SCENARIOS.values()):
        build_data(d)
    return d


def _resolve(spec: str, root: Path) -> Run:
    """ref:<имя> — прогон автора из eval/reference-run.json; путь к .json; имя в eval/out/runs/."""
    if spec.startswith("ref:"):
        store = load_store(root / REF)
        return Run.from_dict(store["runs"][spec[4:]])
    for cand in (Path(spec), root / spec, root / "eval" / "out" / "runs" / f"{spec}.json"):
        if cand.exists():
            return load_run(cand)
    raise SystemExit(f"нет прогона {spec}: укажите ref:<имя>, путь или имя из eval/out/runs/")


def _client():
    import anthropic
    return anthropic.Anthropic()


def _live_ok(run: Run, suite, data: Path) -> dict[str, bool]:
    con, _ = open_scenario(data, run.meta.get("scenario", "base"))
    try:
        return {q: v.correct for q, v in check_live(run, suite, con).items()}
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    a = _p().parse_args(argv)
    root = Path(a.root).resolve()
    suite = load_suite(root / "eval" / "questions.yaml")

    if a.cmd == "data":
        for name, path in build_data(root / "data").items():
            print(f"данные: {name}")
        return 0
    data = _data(root)

    if a.cmd == "refs":
        con, _ = open_scenario(data, a.scenario)
        try:
            bad = []
            for q in suite.questions:
                exp, bites = expected(con, q), trap_bites(con, q)
                trap = f"ловушка {scalar(con, q.trap_sql):,.2f}" if q.trap_sql else "контрольный"
                print(f"{q.id} {q.tag:<11} эталон {exp:>16,.2f}  {trap}{'' if bites else '  ← ЛОВУШКА НЕ КУСАЕТ'}")
                if not bites:
                    bad.append(q.id)
        finally:
            con.close()
        return 1 if bad else 0

    if a.cmd == "freeze":
        con, _ = open_scenario(data, a.scenario)
        try:
            values = freeze(suite, con)
        finally:
            con.close()
        out = root / a.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"scenario": a.scenario, "values": values}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"записано {len(values)} чисел: {a.out}")
        return 0

    if a.cmd == "run":
        if a.model not in PRICES:
            print(f"нет цены для модели {a.model}: добавьте её в PRICES (src/razbor03/agent.py)")
            return 2
        only = {x.strip() for x in a.only.split(",") if x.strip()} | {q.id for q in suite.questions if a.tag and q.tag == a.tag}
        client, factory = _client(), load_factory(a.agent)
        name = a.name or f"{a.scenario}-{a.variant}"
        for i in range(1, a.repeats + 1):
            con, cat = open_scenario(data, a.scenario)
            try:
                agent = factory(con=con, catalog=cat, variant=a.variant, model=a.model, client=client)
                run = run_suite(agent, suite, f"{name}-{i}", {"agent": a.agent, "variant": a.variant, "model": a.model,
                                                             "scenario": a.scenario}, only=only or None,
                                on_answer=lambda x: print(f"{x.qid} {x.value} ${x.cost_usd:.4f} {x.seconds:.1f}s {x.stop}"))
            finally:
                con.close()
            path = save_run(run, root / "eval" / "out" / "runs" / f"{run.name}.json")
            ok = _live_ok(run, suite, data)
            print(f"{run.name}: верно {sum(ok.values())} из {len(ok)}, ${sum(x.cost_usd for x in run.answers):.3f} → {path.relative_to(root)}")
        return 0

    if a.cmd == "check":
        run = _resolve(a.run, root)
        if a.by == "live":
            con, _ = open_scenario(data, run.meta.get("scenario", "base"))
            try:
                vs = check_live(run, suite, con)
            finally:
                con.close()
        else:
            frozen = json.loads((root / a.frozen).read_text(encoding="utf-8"))["values"]
            vs = check_frozen(run, suite, frozen)
        values = run.by_qid()
        for q, v in vs.items():
            print(f"{q} {'OK ' if v.correct else 'ERR'} {values[q].value} / {v.expected:,.2f}")
        print(f"{run.name}: верно {sum(v.correct for v in vs.values())} из {len(vs)} ({a.by})")
        return 0

    if a.cmd == "judge":
        run = _resolve(a.run, root)
        vs = check_judge(run, suite, _client(), a.model,
                         on_verdict=lambda q, v: print(f"{q} {'верно  ' if v.correct else 'неверно'} {v.note}"))
        con, _ = open_scenario(data, run.meta.get("scenario", "base"))
        try:
            ag = agreement(check_live(run, suite, con), vs)
        finally:
            con.close()
        out = root / "eval" / "out" / "judge" / f"{run.name}.{a.model.replace('/', '_')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(verdicts_to_dict(vs), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"судья {a.model}: пропустил ошибок {len(ag['missed'])} из {ag['errors']} {ag['missed']}, "
              f"отверг верных {len(ag['rejected'])} {ag['rejected']}, ${sum(v.cost_usd for v in vs.values()):.3f}")
        return 0

    if a.cmd == "stability":
        runs = [_resolve(r, root) for r in a.runs]
        s = stability([_live_ok(r, suite, data) for r in runs])
        print(json.dumps({k: v for k, v in s.items() if k != "always"}, ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "compare":
        old = [_live_ok(_resolve(r, root), suite, data) for r in a.old]
        new = [_live_ok(_resolve(r, root), suite, data) for r in a.new]
        g = compare(old, new, allow=a.allow)
        print(f"вопросов: {len(g.questions)}; верно было {g.old_correct:g}, стало {g.new_correct:g}")
        print(f"регрессии: {', '.join(g.regressions) or 'нет'}; починено: {', '.join(g.fixed) or 'нет'}; "
              f"плавали до правки: {', '.join(g.flaky_before) or 'нет'}")
        print("ворота: " + ("пропустить" if g.ok else "НЕ ПРОПУСКАТЬ"))
        return g.exit_code

    if a.cmd == "import-01":
        path = root / a.store
        store = load_store(path)
        for run in import_01(a.results):
            store["runs"][run.name] = run.to_dict()
            print(f"{run.name}: {len(run.answers)} ответов")
        save_store(store, path)
        return 0

    if a.cmd == "all":
        out = root / "eval" / "out"
        if a.offline:
            store = load_store(root / REF)
            summary = summarize(store, suite, data)
            stored = store.get("summary") or {}
            same = json.dumps(_public(summary), sort_keys=True) == json.dumps(_public(stored), sort_keys=True)
            print("сводка пересчитана по ответам автора: " + ("совпадает с eval/reference-run.json" if same
                                                              else "РАСХОДИТСЯ с eval/reference-run.json"))
            meta = {"model": store["meta"].get("model"), "source": "прогон автора (eval/reference-run.json), офлайн"}
        else:
            if a.model not in PRICES:
                print(f"нет цены для модели {a.model}")
                return 2
            path = out / "experiment.json"
            store = load_store(path)
            judges = JUDGES if a.model.startswith("anthropic/") else tuple(_direct(j) for j in JUDGES)
            execute(store, suite, data, _client(), model=a.model, judges=judges, save=lambda s: save_store(s, path),
                    max_usd=a.max_usd)
            summary = summarize(store, suite, data)
            store["summary"] = _public(summary)
            save_store(store, path)
            same = True
            meta = {"model": a.model, "source": "ваш прогон (eval/out/experiment.json)"}
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(json.dumps(_public(summary), ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "report.html").write_text(render(summary, store, suite, meta), encoding="utf-8")
        print(json.dumps(_brief(summary), ensure_ascii=False, indent=1))
        print("отчёт: eval/out/report.html")
        return 0 if same else 1
    return 2


def _direct(model: str) -> str:
    """Имя OpenRouter → имя Claude API: anthropic/claude-haiku-5.5 → claude-haiku-5-5."""
    return model.split("/", 1)[1].replace(".", "-")


def _public(summary: dict) -> dict:
    """Сводка без пересчитываемых вердиктов по каждому ответу."""
    return {k: v for k, v in summary.items() if k != "live"}


def _brief(summary: dict) -> dict:
    s = _public(summary)
    out = {"прогоны": {n: f"{r['correct']}/{r['n']}" for n, r in s.get("runs", {}).items()}}
    if "checkers" in s:
        out["проверяющие"] = {k: f"пропустил {len(v['missed'])} из {v['errors']}, отверг {len(v['rejected'])}"
                              for k, v in s["checkers"].items()}
    if "drift" in s:
        out["дозагрузка"] = {k: f"замороженный: отверг верных {len(v['frozen']['rejected'])}, принял неверных "
                                f"{len(v['frozen']['missed'])}" for k, v in s["drift"].items()}
    out["устойчивость"] = {v: f"pass@1 {100 * x['pass_at_1']:.1f} %, pass^{x['k']} {100 * x['pass_hat_k']:.1f} %, "
                              f"плавают {', '.join(x['flaky']) or 'нет'}" for v, x in s.get("stability", {}).items()}
    out["ворота"] = {k: f"код {g['exit_code']}, регрессии {', '.join(g['regressions']) or 'нет'}"
                     for k, g in s.get("gate", {}).items()}
    out["затраты, $"] = s.get("cost_usd_total")
    return out


if __name__ == "__main__":
    sys.exit(main())
