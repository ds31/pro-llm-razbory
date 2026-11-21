import duckdb
from razbor01.cli import main as razbor01_main
from razbor01.golden import load_questions
from razbor01.metrics import load_catalog

from razbor06.accept import evaluate
from razbor06.answers import load_recorded, load_results_jsonl
from razbor06.export import export_agent_root
from razbor06.paths import PKG01
from razbor06.scaffold import scaffold

WORKS = {"tolerance_pct": 0.5, "every_case_answered": True, "max_cost_usd": 0.05, "max_seconds": 15}


def _verdict(db, cases, answers):
    con = duckdb.connect(str(db), read_only=True)
    try:
        return evaluate(con, load_catalog(PKG01 / "metrics.yaml"), cases, answers, "B", layer=True, works_when=WORKS)
    finally:
        con.close()


def test_export_writes_razbor01_root(db, filled, tmp_path):
    cases = scaffold(filled)
    v = _verdict(db, cases, load_recorded(PKG01))
    root = export_agent_root(v.waiting, tmp_path / "agent-root", db)
    qs = load_questions(root / "eval" / "questions.yaml")
    assert len(qs) == 12 and {q.trap for q in qs} == {"none"}
    assert qs[0].question == "Какая выручка магазина №1 за сентябрь 2026 года, в рублях?"
    assert qs[0].metric_query["filters"] == {"store_id": [1]}
    assert (root / "metrics.yaml").read_text(encoding="utf-8") == (PKG01 / "metrics.yaml").read_text(encoding="utf-8")
    assert (root / "data" / "retail.duckdb").exists()


def test_offline_run_of_export_closes_acceptance(db, filled, tmp_path):
    """Конвейер целиком: экспорт → razbor01 eval (офлайн-эталон вместо агента) → accept. Это проверка труб, не агента."""
    cases = scaffold(filled)
    recorded = load_recorded(PKG01)
    root = export_agent_root(_verdict(db, cases, recorded).waiting, tmp_path / "agent-root", db)
    assert razbor01_main(["eval", "--root", str(root), "--offline", "--variants", "B"]) == 0
    extra = load_results_jsonl(root / "eval" / "out" / "results.jsonl")
    assert len(extra) == 12
    v = _verdict(db, cases, {**recorded, **extra})
    assert v.verdict == "принят" and v.answered == 18
