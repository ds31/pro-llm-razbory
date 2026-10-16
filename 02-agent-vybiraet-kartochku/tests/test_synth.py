from conftest import ROOT
from razbor02.synth import COLUMNS, SEED, gtin_ok, make_catalog, to_csv

DEFECT_OK = {"gtin"}  # GTIN может быть «испорчен» (ошибка контрольной цифры), остальные поля только теряются


def test_generator_is_deterministic():
    assert make_catalog(SEED) == make_catalog(SEED)
    assert make_catalog(SEED) != make_catalog(SEED + 1)


def test_catalog_size_and_columns():
    cards, erp = make_catalog(SEED)
    assert 55 <= len(cards) <= 65 and len(cards) == len(erp)
    assert all(list(r) == COLUMNS for r in cards + erp)
    assert len({r["sku"] for r in cards}) == len(cards)
    assert {r["category"] for r in cards} == {"Обувь", "Одежда", "Дом"}


def test_erp_is_complete_and_valid():
    _, erp = make_catalog(SEED)
    for r in erp:
        assert all(r[c] != "" for c in COLUMNS if c not in ("sizes", "target_gender")), r["sku"]
        assert gtin_ok(r["gtin"]) and r["currency"] == "RUB" and r["available"] in ("true", "false")


def test_card_only_loses_fields_never_invents():
    cards, erp = make_catalog(SEED)
    for c, t in zip(cards, erp):
        assert c["sku"] == t["sku"]
        for col in COLUMNS:
            if c[col] != t[col]:
                assert c[col] == "" or col in DEFECT_OK, (c["sku"], col)


def test_cards_have_gaps_of_every_kind():
    cards, erp = make_catalog(SEED)
    for col in ["color", "sizes", "target_gender", "gtin", "available", "ships_to", "delivery_days",
                "rating_count", "currency", "tech_specs", "image_alt"]:
        assert any(c[col] != t[col] for c, t in zip(cards, erp)), col
    assert any(c["gtin"] and not gtin_ok(c["gtin"]) for c in cards)


def test_gtin_checksum():
    assert gtin_ok("4600000000008") is True
    assert gtin_ok("4600000000009") is False
    assert gtin_ok("") is False and gtin_ok("46000") is False


def test_committed_csv_matches_generator():
    cards, erp = make_catalog(SEED)
    assert (ROOT / "data" / "catalog.csv").read_text(encoding="utf-8") == to_csv(cards)
    assert (ROOT / "data" / "catalog_1c.csv").read_text(encoding="utf-8") == to_csv(erp)
