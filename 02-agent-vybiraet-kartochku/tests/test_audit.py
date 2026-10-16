import pytest

from conftest import ROOT
from razbor02.audit import (blame, check_rule, evaluate, in_pool, load_rules, load_scenarios, readiness,
                            run_audit, scenario_steps, step_passes)
from razbor02.synth import SEED, make_catalog

RULES = load_rules(ROOT / "audit" / "rules.yaml")
SCEN = {s["id"]: s for s in load_scenarios(ROOT / "eval" / "scenarios.yaml")}

FULL = {
    "sku": "X-1", "title": "Кроссовки мужские непромокаемые Тест 1", "category": "Обувь", "product_type": "Кроссовки",
    "brand": "Тест", "description": "Удобная модель на каждый день: мягкая амортизация и устойчивая колодка.",
    "color": "Черный", "sizes": "41;42;43", "target_gender": "Мужской", "gtin": "4600000000008", "price": "7490",
    "currency": "RUB", "available": "true", "ships_to": "RU;BY", "delivery_days": "2-4", "rating": "4.6",
    "rating_count": "35", "image_url": "https://example.com/x.jpg", "image_alt": "Кроссовки",
    "tech_specs": "Мембрана: водонепроницаемая; Подошва: резина; Сезон: демисезон",
}


def card(**kw):
    return {**FULL, **kw}


def rule(rid):
    return next(r for r in RULES["rules"] if r["id"] == rid)


# --- правила ---------------------------------------------------------------

def test_every_rule_points_to_shop_mcp_and_weights_sum_to_100():
    ids = [r["id"] for r in RULES["rules"]]
    assert len(ids) == len(set(ids))
    assert all(r["shop_mcp"] and r["why"] and r["label"] for r in RULES["rules"])
    assert sum(r["weight"] for r in RULES["rules"]) == 100
    joined = " ".join(r["shop_mcp"] for r in RULES["rules"])
    for ref in ["name=Color", "name=Size", "name=Target gender", "rating.variant", "min_count", "ships_to",
                "filters.price", "available", "lookup_catalog", "tech_specs"]:
        assert ref in joined, ref


@pytest.mark.parametrize("rid,bad", [
    ("color", {"color": ""}),
    ("size", {"sizes": ""}),
    ("target_gender", {"target_gender": ""}),
    ("gtin", {"gtin": ""}),
    ("gtin", {"gtin": "4600000000009"}),
    ("availability", {"available": ""}),
    ("ships_to", {"ships_to": ""}),
    ("delivery_days", {"delivery_days": ""}),
    ("price_currency", {"currency": ""}),
    ("price_currency", {"price": ""}),
    ("rating_count", {"rating_count": ""}),
    ("rating_count", {"rating_count": "12"}),
    ("rating_count", {"rating": ""}),
    ("tech_specs", {"tech_specs": "Подошва: резина; Сезон: лето"}),
    ("description", {"description": ""}),
    ("image_alt", {"image_alt": ""}),
])
def test_rule_catches_gap(rid, bad):
    assert check_rule(rule(rid), FULL, RULES) is True
    assert check_rule(rule(rid), card(**bad), RULES) is False


def test_readiness_score():
    assert readiness(FULL, RULES) == (100, [])
    score, failed = readiness(card(color=""), RULES)
    assert score == 90 and [r["id"] for r in failed] == ["color"]
    home = card(category="Дом", target_gender="")
    assert readiness(home, RULES)[0] == 100  # пол для товаров дома не нужен
    score, failed = readiness(card(color="", sizes="", image_alt=""), RULES)
    assert [r["id"] for r in failed] == ["size", "color", "image_alt"]  # по убыванию веса
    assert score == 75


# --- сценарии ---------------------------------------------------------------

def test_five_scenarios_in_shop_mcp_shape():
    assert list(SCEN) == ["S1", "S2", "S3", "S4", "S5"]
    s1 = SCEN["S1"]["filters"]
    assert {a["name"] for a in s1["attributes"]} == {"Target gender", "Size"}
    assert s1["rating"]["variant"] == {"min": 4.0, "min_count": 20} and s1["ships_to"]["country"] == "RU"
    assert SCEN["S5"]["tool"] == "lookup_catalog"


def test_steps_follow_filters():
    assert [s[0] for s in scenario_steps(SCEN["S1"])] == [
        "attr:Target gender", "attr:Size", "price", "ships_to", "available", "rating", "verify"]
    assert [s[0] for s in scenario_steps(SCEN["S5"])] == ["lookup", "ships_to", "available"]


@pytest.mark.parametrize("bad,step", [
    ({"sizes": "40;41"}, "attr:Size"),
    ({"sizes": ""}, "attr:Size"),
    ({"target_gender": ""}, "attr:Target gender"),
    ({"price": "8490"}, "price"),
    ({"currency": ""}, "price"),
    ({"ships_to": ""}, "ships_to"),
    ({"available": ""}, "available"),
    ({"available": "false"}, "available"),
    ({"rating_count": ""}, "rating"),
    ({"rating": "3.9"}, "rating"),
    ({"title": "Кроссовки мужские Тест 1", "tech_specs": ""}, "verify"),
])
def test_s1_step_cuts_card(bad, step):
    s = SCEN["S1"]
    assert all(step_passes(st, s, FULL) for st, *_ in scenario_steps(s))
    failed = [st for st, *_ in scenario_steps(s) if not step_passes(st, s, card(**bad))]
    assert failed == [step]


def test_size_matches_whole_value_not_substring():
    s = SCEN["S2"]
    jacket = card(category="Одежда", product_type="Куртка", target_gender="Женский", sizes="XS;S;XL", color="Черный",
                  price="9990", tech_specs="Утеплитель: пух")
    assert not step_passes("attr:Size", s, jacket)


def test_ships_to_is_a_country_list():
    s3 = SCEN["S3"]
    assert step_passes("ships_to", s3, card(ships_to="RU;BY;KZ"))
    assert not step_passes("ships_to", s3, card(ships_to="RU"))


def test_lookup_needs_valid_gtin():
    s5 = SCEN["S5"]
    assert step_passes("lookup", s5, FULL)
    assert not step_passes("lookup", s5, card(gtin="4600000000009"))


def test_pool_is_built_from_erp_truth():
    assert in_pool(SCEN["S1"], FULL)
    assert not in_pool(SCEN["S1"], card(target_gender="Женский"))
    assert not in_pool(SCEN["S1"], card(product_type="Ботинки"))


def test_blame_names_fields_that_differ_from_erp():
    c = card(currency="", rating_count="")
    assert blame("price", SCEN["S1"], c, FULL) == ["currency"]
    assert blame("rating", SCEN["S1"], c, FULL) == ["rating_count"]
    assert blame("price", SCEN["S1"], c, None) == ["currency"]  # без учётной системы — пустые поля шага


# --- на синтетическом каталоге ---------------------------------------------

@pytest.fixture(scope="module")
def catalog():
    return make_catalog(SEED)


def test_each_scenario_has_a_pool_and_loses_cards(catalog):
    cards, erp = catalog
    for s in SCEN.values():
        r = evaluate(s, cards, erp)
        assert r["pool"] >= 3, s["id"]
        assert 0 <= r["visible"] < r["pool"], s["id"]
        assert sum(f["cut"] for f in r["funnel"]) == r["pool"] - r["visible"]


def test_lost_cards_are_fixed_by_copying_blamed_fields(catalog):
    cards, erp = catalog
    by_sku = {e["sku"]: e for e in erp}
    for s in SCEN.values():
        r = evaluate(s, cards, erp)
        for lost in r["lost"]:
            c = next(x for x in cards if x["sku"] == lost["sku"])
            fixed = {**c, **{f: by_sku[c["sku"]][f] for f in lost["fields"]}}
            assert all(step_passes(st, s, fixed) for st, *_ in scenario_steps(s)), (s["id"], lost)
            assert 1 <= len(lost["fields"])


def test_without_erp_pool_is_category(catalog):
    cards, _ = catalog
    r = evaluate(SCEN["S1"], cards, None)
    assert r["pool"] == sum(1 for c in cards if c["category"] == "Обувь" and c["product_type"] == "Кроссовки")


def test_run_audit_summary_shape(catalog):
    cards, erp = catalog
    res = run_audit(cards, erp, RULES, list(SCEN.values()))
    a = res["summary"]
    assert a["cards"] == 60
    assert len(a["scenarios"]) == 5 and len(a["top_blockers"]) == 5
    counts = [b["hits"] for b in a["top_blockers"]]
    assert counts == sorted(counts, reverse=True)
    fx = a["fixable"]
    assert fx["1"] + fx["2"] + fx["3+"] == a["lost_cards"]
    assert 0 <= a["readiness"]["mean"] <= 100
    assert len(res["cards"]) == 60 and {"sku", "score", "missing"} <= set(res["cards"][0])
