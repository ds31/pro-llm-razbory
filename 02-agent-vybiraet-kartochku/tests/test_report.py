import json
import re

import pytest

from conftest import FIXTURES, ROOT
from razbor02 import mcp
from razbor02.audit import load_rules, load_scenarios, run_audit
from razbor02.report import render_report
from razbor02.synth import SEED, make_catalog


@pytest.fixture(scope="module")
def html(tmp_path_factory):
    out = tmp_path_factory.mktemp("live")
    summary = mcp.run_probe(out, FIXTURES, offline=True)
    payloads = {k: mcp.parse_search(json.loads((out / f"{k}.json").read_text(encoding="utf-8")))
                for k in ["search", "search-base", "search-filtered"]}
    cards, erp = make_catalog(SEED)
    audit = run_audit(cards, erp, load_rules(ROOT / "audit" / "rules.yaml"),
                      load_scenarios(ROOT / "eval" / "scenarios.yaml"))
    return render_report(summary, payloads, audit)


def test_three_screens_with_anchors(html):
    for anchor in ['id="tools"', 'id="search"', 'id="audit"']:
        assert anchor in html


def test_no_external_resources(html):
    assert not re.search(r'<link[^>]+href="https?://', html)
    assert "@import" not in html and "<script src" not in html


def test_site_palette_and_fonts(html):
    for token in ["#f7f5ee", "#14181d", "#0b7d4f", "Onest", "JetBrains Mono"]:
        assert token in html


def test_tools_screen_lists_tools_and_request(html):
    for name in ["search_catalog", "lookup_catalog", "create_checkout", "complete_checkout"]:
        assert name in html
    assert "MCP-Protocol-Version" in html and "2026-07-28" in html and "Target gender" in html


def test_search_screen_shows_filter_effect(html):
    assert "min_count" in html
    assert re.search(r"1\s*из\s*50", html)


def test_audit_screen_shows_scenarios_and_blockers(html):
    for sid in ["S1", "S2", "S3", "S4", "S5"]:
        assert f">{sid}<" in html
    assert "Число отзывов" in html or "Пол" in html


def test_titles_are_escaped():
    payload = {"ucp": {"version": "v"}, "products": [{"id": "1", "title": "<script>x</script>", "variants": []}]}
    s = mcp.summarize({"tools": json.loads((FIXTURES / "tools.json").read_text(encoding="utf-8")),
                       "search": {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}},
                       "search-base": {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}},
                       "search-filtered": {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}},
                      "fixtures", "", "2026-10-17")
    cards, erp = make_catalog(SEED)
    audit = run_audit(cards, erp, load_rules(ROOT / "audit" / "rules.yaml"), load_scenarios(ROOT / "eval" / "scenarios.yaml"))
    out = render_report(s, {"search": payload, "search-base": payload, "search-filtered": payload}, audit)
    assert "<script>x</script>" not in out and "&lt;script&gt;" in out
