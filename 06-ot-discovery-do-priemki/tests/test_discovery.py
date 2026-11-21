import yaml

from razbor06.discovery import check, load_discovery
from conftest import EXAMPLES


def fields(rep, where):
    return {g.field for g in rep.gaps if g.where == where}


def test_filled_example_is_ready(filled, catalog_ids):
    rep = check(filled, catalog_ids)
    assert rep.gaps == []
    assert rep.ready


def test_day1_example_is_not_ready(catalog_ids):
    rep = check(load_discovery(EXAMPLES / "discovery-day1.yaml"), catalog_ids)
    assert not rep.ready
    # у каждого вопроса нет владельца, эталона и решения
    for q in ("M1", "M2", "M3"):
        assert {"owner", "golden", "decision", "definition", "period"} <= fields(rep, q), q
    assert "metric" in fields(rep, "M1")          # «выручка» — слово, а не метрика каталога
    assert "metric" in fields(rep, "M2") and "sources" in fields(rep, "M3")
    assert "asked_by" in fields(rep, "M2")        # «Руководитель закупок» не в списке участников
    assert {"owner", "refresh"} <= fields(rep, "data_map:raw.sales")


def test_every_question_needs_metric_source_owner_golden(filled, catalog_ids):
    q = filled["questions"][0]
    for key in ("metric", "sources", "owner", "golden"):
        q.pop(key)
    assert {"metric", "sources", "owner", "golden"} <= fields(check(filled, catalog_ids), "M1")


def test_metric_must_exist_in_catalog(filled, catalog_ids):
    filled["questions"][0]["metric"] = "revenue_v2"
    gaps = [g for g in check(filled, catalog_ids).gaps if g.where == "M1" and g.field == "metric"]
    assert gaps and "revenue_v2" in gaps[0].text


def test_ratio_metric_parts_checked(filled, catalog_ids):
    filled["questions"][2]["metric"] = "returns_amount / returns_share"
    assert "metric" in fields(check(filled, catalog_ids), "M3")


def test_catalog_is_optional(filled):
    filled["questions"][0]["metric"] = "что-угодно"
    assert check(filled, None).ready


def test_source_must_be_in_data_map(filled, catalog_ids):
    filled["questions"][0]["sources"].append("raw.loyalty")
    gaps = [g for g in check(filled, catalog_ids).gaps if g.where == "M1" and g.field == "sources"]
    assert gaps and "raw.loyalty" in gaps[0].text


def test_owner_must_be_stakeholder_and_sign_golden(filled, catalog_ids):
    filled["questions"][0]["golden"]["signed_by"] = "Руководитель ИТ"
    assert "golden.signed_by" in fields(check(filled, catalog_ids), "M1")
    filled["questions"][0]["owner"] = "Бухгалтер"
    assert "owner" in fields(check(filled, catalog_ids), "M1")


def test_golden_needs_sql_and_signature(filled, catalog_ids):
    g = filled["questions"][1]["golden"]
    g.pop("sql")
    g.pop("signed_on")
    assert {"golden.sql", "golden.signed_on"} <= fields(check(filled, catalog_ids), "M2")


def test_issue_of_used_source_must_be_covered(filled, catalog_ids):
    m1 = filled["questions"][0]
    m1["checks"] = [c for c in m1["checks"] if "issue:anomaly" not in c["covers"]]
    gaps = [g for g in check(filled, catalog_ids).gaps if g.where == "M1" and g.field == "coverage"]
    assert len(gaps) == 1 and "issue:anomaly" in gaps[0].text and "9999" in gaps[0].text


def test_relative_period_issue_only_for_relative_questions(filled, catalog_ids):
    # open_month касается только вопросов «за прошлый месяц»: M3 задан явным кварталом
    assert "coverage" not in fields(check(filled, catalog_ids), "M3")
    filled["questions"][2]["relative_period"] = True
    assert "coverage" in fields(check(filled, catalog_ids), "M3")


def test_alternative_definition_must_be_covered(filled, catalog_ids):
    filled["questions"][1]["checks"] = []
    texts = [g.text for g in check(filled, catalog_ids).gaps if g.where == "M2" and g.field == "coverage"]
    assert any("alt:stock_avg_units" in t for t in texts)


def test_check_needs_question_query_and_golden(filled, catalog_ids):
    c = filled["questions"][0]["checks"][0]
    c.pop("golden_sql")
    c.pop("metric_query")
    assert {"checks[1].golden_sql", "checks[1].metric_query"} <= fields(check(filled, catalog_ids), "M1")


def test_breakdown_needs_row_question(filled, catalog_ids):
    filled["questions"][0].pop("row_question")
    assert "row_question" in fields(check(filled, catalog_ids), "M1")


def test_issues_outside_questions_are_listed(filled, catalog_ids):
    rep = check(filled, catalog_ids)
    assert rep.untouched_issues == [("raw.products", "dup_cards")]


def test_duplicate_question_ids(filled, catalog_ids):
    filled["questions"][1]["id"] = "M1"
    assert any(g.field == "id" for g in check(filled, catalog_ids).gaps)


def test_template_parses_and_is_not_ready(catalog_ids):
    from razbor06.paths import ROOT
    rep = check(load_discovery(ROOT / "templates" / "discovery.yaml"), catalog_ids)
    assert not rep.ready and rep.questions == ["M1"]


def test_load_discovery_rejects_non_mapping(tmp_path):
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump(["не словарь"]), encoding="utf-8")
    try:
        load_discovery(p)
    except ValueError as e:
        assert "discovery" in str(e)
    else:
        raise AssertionError("ожидали ValueError")
