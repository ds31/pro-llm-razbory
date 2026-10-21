from pathlib import Path

import pytest

from razbor05.rules import RULES_DIR, RuleError, load_rules, parse_rule


def test_all_rules_have_passport():
    rules = load_rules()
    ids = [r.id for r in rules]
    assert ids == ["C01", "R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09"]
    for r in rules:
        assert r.why and len(r.why) > 40, r.id
        assert r.sql.lstrip().startswith("--")


def test_block_and_warn_split():
    sev = {r.id: (r.severity, r.action) for r in load_rules()}
    assert sev["R01"] == ("block", "drop") and sev["R02"] == ("block", "drop")
    assert all(sev[i] == ("block", "hold") for i in ("R03", "R04", "R05", "R06", "R09", "C01"))
    assert sev["R07"] == ("warn", "pass") and sev["R08"] == ("warn", "pass")


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body, encoding="utf-8")
    return p


GOOD = "-- R10 · Тест\n-- table: sales\n-- severity: block\n-- action: drop\n-- fix: none\n-- why: потому что.\nSELECT 1"


def test_parse_good(tmp_path):
    r = parse_rule(_write(tmp_path, "R10_test.sql", GOOD))
    assert (r.id, r.table, r.severity, r.action) == ("R10", "sales", "block", "drop")


@pytest.mark.parametrize("broken, msg", [
    (GOOD.replace("-- severity: block\n", ""), "severity"),
    (GOOD.replace("block", "warn"), "warn"),
    (GOOD.replace("table: sales", "table: orders"), "table"),
    (GOOD.replace("-- R10 · Тест", "-- правило"), "первая строка"),
])
def test_parse_rejects_broken_passport(tmp_path, broken, msg):
    with pytest.raises(RuleError, match=msg):
        parse_rule(_write(tmp_path, "R10_test.sql", broken))


def test_file_name_matches_id(tmp_path):
    with pytest.raises(RuleError, match="имя файла"):
        parse_rule(_write(tmp_path, "R11_test.sql", GOOD))


def test_rules_dir_is_package_rules():
    assert RULES_DIR.name == "rules" and (RULES_DIR / "close").is_dir()
