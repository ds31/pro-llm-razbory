"""Проверка агентом B пакета 01: одна и та же витрина за воротами, разный closed_through.

Утро 03.11.2026, сценарий «всё сразу»: октябрь ещё не прошёл чек-лист (нет файла магазина №4 за 31.10, снимок
остатков магазина №4 в карантине). Агент B пакета 01 отвечает на вопросы про «последний месяц» дважды:
- `calendar`: closed_through = 31.10 — «по календарю, 1-го числа месяц закрыт»;
- `gates`:    closed_through = 30.09 — от ворот.
Правда для ответа — тот месяц, который агент назвал последним: октябрь для calendar, сентябрь для gates.
Без ключа (`offline`) ответы — эталонные запросы слоя метрик; это проверка конвейера, а не агента.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import duckdb

from razbor01.agent import PRICES, run_agent
from razbor01.golden import is_correct
from razbor01.runner import scrub
from razbor01.tools import make_toolbox, open_db

from .experiment import run_showcase, showcase_feed
from .feed import FeedFiles
from .modes import Truth
from .questions import QUESTIONS, answer_all, catalog

AS_OF = date(2026, 11, 3)
QIDS = ["Q19", "Q21", "Q23", "Q24", "N1", "N2", "N3"]
SETUPS = {"calendar": date(2026, 10, 31), "gates": date(2026, 9, 30)}


@dataclass
class AgentAnswer:
    setup: str
    qid: str
    question: str
    closed_through: str
    expected: float | None
    got: float | None
    correct: bool
    explanation: str
    metric_id: str | None
    cost_usd: float
    seconds: float
    stop: str
    trace: list


def prepare(base: Path | str, db_path: Path | str) -> dict:
    """Витрина ворот на утро AS_OF → файл DuckDB; правда для сентября и октября."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    state = {}

    def inspect(modes):
        m = modes["gate"]
        m.build_mart()
        state["gate_closed_through"] = m.closed_through(AS_OF).isoformat()
        m.con.execute(f"ATTACH '{db_path.as_posix()}' AS snap")
        m.con.execute("CREATE SCHEMA snap.mart")
        for (t,) in m.con.execute("SELECT table_name FROM information_schema.tables "
                                  "WHERE table_catalog = 'memory' AND table_schema = 'mart'").fetchall():
            m.con.execute(f"CREATE TABLE snap.mart.{t} AS SELECT * FROM mart.{t}")
        m.con.execute("DETACH snap")

    run_showcase(base, "all", keys=("gate",), until=AS_OF, inspect=inspect)
    feed, _ = showcase_feed(base, "all")
    with FeedFiles(feed) as ff:
        t = Truth(base, ff)
        state["truth"] = {k: answer_all(t.con, ct) for k, ct in SETUPS.items()}
        t.close()
    return state


def run(base: Path | str, db_path: Path | str, client=None, model: str = "anthropic/claude-sonnet-5.5",
        only: list[str] | None = None, setups=("calendar", "gates")) -> tuple[list[AgentAnswer], dict]:
    state = prepare(base, db_path)
    qs = [q for q in QUESTIONS if q.id in (only or QIDS)]
    out = []
    con = open_db(db_path)
    try:
        for setup in setups:
            ct = SETUPS[setup]
            cat = catalog(ct)
            box = make_toolbox("B", con, cat)
            oracle = answer_all(con, ct)
            for q in qs:
                exp = state["truth"][setup][q.id]
                if client is None:
                    got, expl, mid, cost, sec, stop, trace = oracle[q.id], "офлайн: эталонный запрос слоя метрик", \
                        None, 0.0, 0.0, "offline", []
                else:
                    r = run_agent(q.text, box, client, model=model)
                    got, expl, mid, cost, sec, stop = r.value, scrub(r.explanation), r.metric_id, \
                        r.cost_usd(model), r.seconds, r.stop
                    trace = [{"tool": c.name, "input": c.input, "output": scrub(c.output)[:600]} for c in r.trace]
                out.append(AgentAnswer(setup, q.id, q.text, ct.isoformat(), exp, got,
                                       exp is not None and is_correct(got, exp), expl, mid, round(cost, 5),
                                       round(sec, 1), stop, trace))
    finally:
        con.close()
    return out, state


def summarize(answers: list[AgentAnswer]) -> dict:
    s = {}
    for a in answers:
        x = s.setdefault(a.setup, {"n": 0, "correct": 0, "cost_usd": 0.0})
        x["n"] += 1
        x["correct"] += a.correct
        x["cost_usd"] = round(x["cost_usd"] + a.cost_usd, 4)
    return s


def to_json(answers, state, model, offline) -> dict:
    return {"meta": {"as_of": AS_OF.isoformat(), "scenario": "all", "model": "офлайн-эталон" if offline else model,
                     "price_usd_per_mtok": None if offline else PRICES.get(model)},
            "gate_closed_through": state["gate_closed_through"],
            "summary": summarize(answers), "answers": [asdict(a) for a in answers]}
