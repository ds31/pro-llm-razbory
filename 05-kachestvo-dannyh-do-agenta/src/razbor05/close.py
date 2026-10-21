"""Закрытие месяца — явный чек-лист, а не дата в календаре.

Месяц закрыт, когда к утру выполнены все пункты `rules/close/K*.sql` (каждый возвращает проблемы; пусто — пункт
выполнен). Тогда в core.closures пишется месяц и день закрытия, и `closed_through` для агента сдвигается.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .rules import RULES_DIR


@dataclass
class Check:
    id: str
    title: str
    ok: bool
    problems: list = field(default_factory=list)


@dataclass
class Closure:
    month: date
    day: date
    closed: bool
    checks: list[Check]

    def summary(self) -> str:
        marks = " · ".join(f"{c.id} {'да' if c.ok else 'нет'}" for c in self.checks)
        return f"{self.month:%Y-%m} на {self.day:%d.%m}: {'закрыт' if self.closed else 'не закрыт'} ({marks})"


def month_end(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1) - timedelta(1)


def load_checks(rules_dir: Path | str = RULES_DIR) -> list[tuple[str, str, str]]:
    """(id, заголовок, sql) из rules/close/K*.sql; {C01} подставляется текстом правила C01."""
    rules_dir = Path(rules_dir)
    c01 = (rules_dir / "C01_missing_store_day.sql").read_text(encoding="utf-8").strip().rstrip(";")
    out = []
    for p in sorted((rules_dir / "close").glob("K*.sql")):
        text = p.read_text(encoding="utf-8")
        m = re.match(r"--\s*(K\d+)\s*·\s*(.+)", text.splitlines()[0])
        sql = text.replace("{C01}", c01).strip().rstrip(";")
        out.append((m.group(1), m.group(2).strip(), sql))
    return out


def check_month(con, month: date, rules_dir: Path | str = RULES_DIR) -> list[Check]:
    params = {"month": month, "month_end": month_end(month), "date_from": month, "date_to": month_end(month)}
    checks = []
    for cid, title, sql in load_checks(rules_dir):
        need = sorted(set(re.findall(r"\$([a-z_]+)", sql)))
        rows = con.execute(sql, {k: params[k] for k in need}).fetchall()
        checks.append(Check(cid, title, not rows, rows))
    return checks


def close_month(con, month: date, day: date, rules_dir: Path | str = RULES_DIR) -> Closure:
    """Прогнать чек-лист месяца к утру day; всё «да» — записать закрытие."""
    checks = check_month(con, month, rules_dir)
    closed = all(c.ok for c in checks)
    if closed:
        con.execute("INSERT INTO core.closures VALUES (?, ?)", [month, day])
    return Closure(month, day, closed, checks)
