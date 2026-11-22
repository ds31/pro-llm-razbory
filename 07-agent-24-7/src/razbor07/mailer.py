"""Почтовый шлюз: письмо магазину — побочный эффект агента, который нельзя «откатить».

Шлюз принимает Idempotency-Key, как платёжные и почтовые API: повтор с тем же ключом не отправляет
второе письмо. Без ключа каждый вызов — новое письмо. Дубль = магазин получил ответ дважды.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path


class MailGateway:
    """Шлюз в памяти для симулятора."""

    def __init__(self):
        self.deliveries: dict[str, list[float]] = defaultdict(list)
        self.keys: set[str] = set()
        self.deduped = 0

    def send(self, now: float, task_key: str, idem_key: str | None) -> bool:
        if idem_key is not None:
            if idem_key in self.keys:
                self.deduped += 1
                return False
            self.keys.add(idem_key)
        self.deliveries[task_key].append(now)
        return True


class SqliteMailGateway:
    """Тот же шлюз на SQLite — для docker compose: журнал писем лежит рядом с очередью."""

    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("CREATE TABLE IF NOT EXISTS mail (id INTEGER PRIMARY KEY, task_key TEXT NOT NULL, "
                        "idem_key TEXT UNIQUE, sent_at REAL NOT NULL)")

    def send(self, now: float, task_key: str, idem_key: str | None) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO mail (task_key, idem_key, sent_at) VALUES (?, ?, ?)",
                              (task_key, idem_key, now))
        return cur.rowcount == 1

    def counts(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT task_key, count(*) FROM mail GROUP BY task_key ORDER BY task_key"))
