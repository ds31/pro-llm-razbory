"""Правила качества данных: SQL-файлы в `rules/` с заголовком-паспортом.

Заголовок файла:
    -- R01 · Название
    -- table: sales | sales_file | stock | products | completeness
    -- severity: block | warn
    -- action: drop | hold | pass        (drop — мусор, hold — ждём исправления, pass — пропустить с предупреждением)
    -- fix: none | resend | wait | reopen  (кто снимает карантин: исправленный файл, справочник, человек)
    -- why: почему правило такое — одной-двумя фразами

Тело — SELECT, который возвращает строки-нарушения: (load_id, row_no, detail), для completeness — (store_id,
business_date, detail). Пустой результат — правило молчит.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

TABLES = {"sales", "sales_file", "stock", "products", "completeness"}
ACTIONS = {"drop", "hold", "pass"}
FIXES = {"none", "resend", "wait", "reopen"}
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = PACKAGE_ROOT / "rules"


class RuleError(ValueError):
    """Паспорт правила заполнен неверно."""


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    table: str
    severity: str
    action: str
    fix: str
    why: str
    sql: str
    path: Path

    @property
    def params(self) -> list[str]:
        return sorted(set(re.findall(r"\$([a-z_]+)", self.sql)))


def parse_rule(path: Path | str) -> Rule:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    m = re.match(r"--\s*([A-Z]\d{2})\s*·\s*(.+)", lines[0] if lines else "")
    if not m:
        raise RuleError(f"{path.name}: первая строка — «-- R01 · Название»")
    meta = {}
    for line in lines[1:]:
        mm = re.match(r"--\s*([a-z]+):\s*(.+)", line)
        if not mm:
            break
        meta[mm.group(1)] = mm.group(2).strip()
    for key in ("table", "severity", "action", "fix", "why"):
        if key not in meta:
            raise RuleError(f"{path.name}: нет поля {key}")
    rule = Rule(m.group(1), m.group(2).strip(), meta["table"], meta["severity"], meta["action"], meta["fix"],
                meta["why"], text.strip().rstrip(";"), path)
    if rule.table not in TABLES:
        raise RuleError(f"{path.name}: table {rule.table} — не из {sorted(TABLES)}")
    if rule.severity not in {"block", "warn"}:
        raise RuleError(f"{path.name}: severity — block или warn")
    if rule.action not in ACTIONS or rule.fix not in FIXES:
        raise RuleError(f"{path.name}: action {rule.action} / fix {rule.fix}")
    if (rule.severity == "warn") != (rule.action == "pass"):
        raise RuleError(f"{path.name}: warn ↔ action: pass, block ↔ drop или hold")
    if not path.stem.startswith(rule.id + "_"):
        raise RuleError(f"{path.name}: имя файла начинается с id правила {rule.id}_")
    return rule


def load_rules(rules_dir: Path | str = RULES_DIR) -> list[Rule]:
    rules = [parse_rule(p) for p in sorted(Path(rules_dir).glob("*.sql"))]
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise RuleError(f"повторяются id правил: {ids}")
    return rules


def run_rule(con, rule: Rule, **params) -> list[tuple]:
    """Выполнить правило; параметры — только те, что есть в тексте ($date_from и т. п.)."""
    need = rule.params
    missing = [p for p in need if p not in params]
    if missing:
        raise RuleError(f"{rule.id}: нужны параметры {missing}")
    return con.execute(rule.sql, {k: params[k] for k in need} if need else None).fetchall()
