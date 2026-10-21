import json

from razbor04.bench import BenchResult, summarize
from razbor04.reference import from_reference, to_reference
from razbor04.report import render_report, scatter_svg


def _r(model, variant, correct, cost, qid="Q01", trap="none", run=1):
    return BenchResult(model=model, variant=variant, run=run, qid=qid, trap=trap, question="Вопрос?", expected=1.0,
                       got=1.0 if correct else 2.0, correct=correct, stop="final_answer", steps=3,
                       tools=["list_metrics", "query_metric", "final_answer"], input_tokens=9000, output_tokens=300,
                       thinking_tokens=0, cost_list_usd=cost, cost_billed_usd=cost, seconds=5.0)


RS = [_r("anthropic/claude-opus-5.5", "A", True, 0.05), _r("anthropic/claude-opus-5.5", "B", True, 0.03),
      _r("deepseek/deepseek-v4.1-flash", "A", False, 0.001), _r("deepseek/deepseek-v4.1-flash", "B", True, 0.0005)]
META = {"дата прогона": "2026-10-21", "вопросов": 1}


def test_scatter_has_point_per_model_variant():
    svg = scatter_svg(summarize(RS))
    assert svg.startswith("<svg") and svg.count('class="pt') == 4
    assert "claude-opus-5.5" in svg and "deepseek-v4.1-flash" in svg


def test_report_sections_and_no_paths():
    html = render_report(RS, summarize(RS), META)
    for part in ['id="summary"', 'id="map"', 'id="traps"', 'id="questions"', "$ за верный ответ", "Ошибок API"]:
        assert part in html
    assert "/home/" not in html and "/tmp/" not in html


def test_reference_roundtrip(tmp_path):
    ref = to_reference(RS, summarize(RS), META)
    p = tmp_path / "ref.json"
    p.write_text(json.dumps(ref, ensure_ascii=False), encoding="utf-8")
    back, meta = from_reference(p)
    assert [(r.model, r.variant, r.correct) for r in back] == [(r.model, r.variant, r.correct) for r in RS]
    assert summarize(back) == summarize(RS) and meta["вопросов"] == 1


def test_jsonl_skips_line_being_written(tmp_path):
    from dataclasses import asdict
    from razbor04.reference import load_jsonl
    p = tmp_path / "m.r1.jsonl"
    p.write_text(json.dumps(asdict(RS[0]), ensure_ascii=False) + "\n" + '{"model": "anthr', encoding="utf-8")
    assert len(load_jsonl([p])) == 1
