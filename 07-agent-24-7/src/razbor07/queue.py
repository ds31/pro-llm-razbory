"""Очередь задач на SQLite: ключ идемпотентности, аренда с продлением, ретраи с backoff, dead-letter.

Одна таблица `tasks`. Задачу берёт воркер на время аренды (lease); пока работает — продлевает её
(heartbeat). Воркер убит kill -9 — аренда истекает, задачу забирает другой: доставка «хотя бы раз».
Время передаётся явно (`now`), поэтому тот же код работает и в симуляторе, и в проде (time.time()).
Для нескольких машин — тот же протокол на Postgres: SELECT … FOR UPDATE SKIP LOCKED.
"""
from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id           INTEGER PRIMARY KEY,
  idem_key     TEXT UNIQUE,              -- ключ идемпотентности от клиента; NULL — без защиты от повторов
  payload      TEXT NOT NULL,
  status       TEXT NOT NULL,            -- queued | leased | done | dead
  attempts     INTEGER NOT NULL DEFAULT 0,
  available_at REAL NOT NULL,            -- раньше этого времени не брать (backoff)
  lease_owner  TEXT,
  lease_until  REAL,
  last_error   TEXT,
  created_at   REAL NOT NULL,
  finished_at  REAL
);
CREATE INDEX IF NOT EXISTS tasks_ready ON tasks (status, available_at);
"""


@dataclass(frozen=True)
class Task:
    id: int
    key: str | None
    payload: dict
    attempt: int
    reclaimed_from: str | None     # чья аренда истекла, если задачу забрали после падения


def backoff(attempt: int, r: random.Random, base: float = 2.0, cap: float = 300.0,
            retry_after: float | None = None) -> float:
    """Экспонента с полным джиттером (AWS Builders' Library); retry-after провайдера — нижняя граница."""
    delay = r.uniform(0.0, min(cap, base * 2 ** attempt))
    return max(delay, retry_after or 0.0)


class Queue:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=30, check_same_thread=False)
        if str(path) != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript(SCHEMA)
        self.reclaimed_dead: list[tuple[int, str]] = []

    # --- API ----------------------------------------------------------------------------------
    def enqueue(self, payload: dict, now: float, key: str | None = None) -> tuple[int, bool]:
        """Поставить задачу. С ключом повтор того же запроса вернёт ту же задачу: (id, создана ли)."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO tasks (idem_key, payload, status, available_at, created_at) "
            "VALUES (?, ?, 'queued', ?, ?)", (key, json.dumps(payload, ensure_ascii=False), now, now))
        if cur.rowcount == 1:
            return cur.lastrowid, True
        (tid,) = self.db.execute("SELECT id FROM tasks WHERE idem_key = ?", (key,)).fetchone()
        return tid, False

    # --- воркер -------------------------------------------------------------------------------
    def claim(self, owner: str, now: float, lease: float, max_attempts: int = 6) -> Task | None:
        """Взять готовую задачу или задачу с истёкшей арендой. Исчерпала попытки — в dead-letter."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            while True:
                row = self.db.execute(
                    "SELECT id, idem_key, payload, attempts, status, lease_owner FROM tasks "
                    "WHERE (status = 'queued' AND available_at <= ?) OR (status = 'leased' AND lease_until < ?) "
                    "ORDER BY available_at, id LIMIT 1", (now, now)).fetchone()
                if row is None:
                    self.db.execute("COMMIT")
                    return None
                tid, key, payload, attempts, status, prev = row
                reclaimed = prev if status == "leased" else None
                if reclaimed and attempts >= max_attempts:
                    self.db.execute("UPDATE tasks SET status = 'dead', last_error = 'lease expired', "
                                    "lease_owner = NULL, finished_at = ? WHERE id = ?", (now, tid))
                    self.reclaimed_dead.append((tid, reclaimed))
                    continue
                self.db.execute("UPDATE tasks SET status = 'leased', attempts = attempts + 1, lease_owner = ?, "
                                "lease_until = ? WHERE id = ?", (owner, now + lease, tid))
                self.db.execute("COMMIT")
                return Task(tid, key, json.loads(payload), attempts + 1, reclaimed)
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def heartbeat(self, tid: int, owner: str, now: float, lease: float) -> bool:
        cur = self.db.execute("UPDATE tasks SET lease_until = ? WHERE id = ? AND status = 'leased' AND lease_owner = ?",
                              (now + lease, tid, owner))
        return cur.rowcount == 1

    def ack(self, tid: int, owner: str, now: float) -> bool:
        cur = self.db.execute("UPDATE tasks SET status = 'done', finished_at = ?, lease_owner = NULL "
                              "WHERE id = ? AND status = 'leased' AND lease_owner = ?", (now, tid, owner))
        return cur.rowcount == 1

    def fail(self, tid: int, owner: str, now: float, error: str, retryable: bool, delay: float,
             max_attempts: int) -> str:
        """Попытка не удалась: «retry» — вернуть в очередь через delay, «dead» — в dead-letter, «lost» — аренда не наша."""
        row = self.db.execute("SELECT attempts FROM tasks WHERE id = ? AND status = 'leased' AND lease_owner = ?",
                              (tid, owner)).fetchone()
        if row is None:
            return "lost"
        if not retryable or row[0] >= max_attempts:
            self.db.execute("UPDATE tasks SET status = 'dead', last_error = ?, lease_owner = NULL, finished_at = ? "
                            "WHERE id = ?", (error, now, tid))
            return "dead"
        self.db.execute("UPDATE tasks SET status = 'queued', last_error = ?, lease_owner = NULL, available_at = ? "
                        "WHERE id = ?", (error, now + delay, tid))
        return "retry"

    # --- оператор -----------------------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT status, count(*) FROM tasks GROUP BY status ORDER BY status").fetchall())

    def dead_letters(self) -> list[dict]:
        rows = self.db.execute("SELECT id, idem_key, attempts, last_error, finished_at FROM tasks "
                               "WHERE status = 'dead' ORDER BY id").fetchall()
        return [dict(id=r[0], key=r[1], attempts=r[2], last_error=r[3], finished_at=r[4]) for r in rows]

    def requeue_dead(self, tid: int, now: float) -> bool:
        """Вернуть задачу из dead-letter после исправления причины (попытки обнуляются)."""
        cur = self.db.execute("UPDATE tasks SET status = 'queued', attempts = 0, available_at = ?, finished_at = NULL "
                              "WHERE id = ? AND status = 'dead'", (now, tid))
        return cur.rowcount == 1

    def get(self, tid: int) -> dict | None:
        r = self.db.execute("SELECT id, idem_key, status, attempts, last_error, created_at, finished_at FROM tasks "
                            "WHERE id = ?", (tid,)).fetchone()
        if r is None:
            return None
        return dict(id=r[0], key=r[1], status=r[2], attempts=r[3], last_error=r[4], created_at=r[5], finished_at=r[6])

    def oldest_queued_age(self, now: float) -> float:
        (t,) = self.db.execute("SELECT min(created_at) FROM tasks WHERE status IN ('queued', 'leased')").fetchone()
        return 0.0 if t is None else now - t
