"""Клиент-нагрузка и проверка итога для docker compose: N вопросов, часть отправлена дважды с тем же ключом."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from .fakellm import rng
from .mailer import SqliteMailGateway
from .queue import Queue
from .sim import QUESTIONS


def post_task(url: str, key: str, payload: dict, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(f"{url.rstrip('/')}/tasks", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Idempotency-Key": key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run_load(url: str, n: int, resend_share: float = 0.1, seed: int = 48, prefix: str = "live") -> dict:
    r = rng(seed, "load", prefix)
    sent = dup = 0
    for i in range(n):
        store = r.randint(1, 60)
        key = f"{prefix}/store-{store:02d}/q-{i + 1:04d}"
        payload = {"store": store, "question": r.choice(QUESTIONS)}
        post_task(url, key, payload)
        sent += 1
        if r.random() < resend_share:  # ответ «потерялся» — бот переспрашивает с тем же ключом
            res = post_task(url, key, payload)
            dup += res["duplicate"]
    return {"tasks": sent, "resent_with_same_key": dup}


def check(db: str | Path, wait: float = 0.0, poll: float = 1.0) -> dict:
    """Итог по базе очереди: статусы, dead-letter, письма и дубли писем. wait — ждать, пока очередь опустеет."""
    q, mail = Queue(db), SqliteMailGateway(db)
    deadline = time.time() + wait
    while True:
        counts = q.counts()
        if not (counts.get("queued") or counts.get("leased")) or time.time() >= deadline:
            break
        time.sleep(poll)
    per_task = mail.counts()
    return {
        "counts": counts,
        "dead_letter": q.dead_letters(),
        "mail_sent": sum(per_task.values()),
        "tasks_with_mail": len(per_task),
        "duplicate_mail": sum(v - 1 for v in per_task.values() if v > 1),
        "max_attempts_seen": q.db.execute("SELECT coalesce(max(attempts), 0) FROM tasks").fetchone()[0],
    }
