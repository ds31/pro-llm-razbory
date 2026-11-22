"""API на стандартной библиотеке: принять задачу и сразу ответить 202. Агента здесь не зовут.

POST /tasks          тело {"store": 12, "question": "…"}, заголовок Idempotency-Key — повтор вернёт ту же задачу
GET  /tasks/<id>     статус задачи
GET  /healthz        жив ли процесс и доступна ли очередь — для healthcheck в docker compose
GET  /stats          глубина очереди, возраст самой старой задачи, dead-letter, писем — для мониторинга
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .mailer import SqliteMailGateway
from .queue import Queue
from .trace import Tracer
from .worker import Clock


def make_server(db: str | Path, host: str = "0.0.0.0", port: int = 8080, clock: Clock | None = None,
                tracer: Tracer | None = None) -> ThreadingHTTPServer:
    q, mail = Queue(db), SqliteMailGateway(db)
    clock = clock or Clock()
    tr = tracer or Tracer(keep=False)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # журнал — структурный, через Tracer
            pass

        def do_POST(self):
            if self.path != "/tasks":
                return self._json(404, {"error": "not found"})
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "bad json"})
            key = self.headers.get("Idempotency-Key")
            payload["key"] = key or payload.get("key") or f"anon/{threading.get_ident()}/{clock.now()}"
            with lock:
                tid, created = q.enqueue(payload, clock.now(), key=key)
            tr.emit(time.time(), "received", task=payload["key"], task_id=tid, duplicate=not created)
            self._json(202, {"task_id": tid, "duplicate": not created})

        def do_GET(self):
            if self.path == "/healthz":
                with lock:
                    q.counts()
                return self._json(200, {"ok": True})
            if self.path == "/stats":
                with lock:
                    counts = q.counts()
                    age = q.oldest_queued_age(clock.now())
                    dead = len(q.dead_letters())
                    mails = sum(mail.counts().values())
                return self._json(200, {"counts": counts, "oldest_queued_age_s": round(age, 1),
                                        "dead_letter": dead, "mail_sent": mails})
            if self.path.startswith("/tasks/"):
                try:
                    tid = int(self.path.rsplit("/", 1)[1])
                except ValueError:
                    return self._json(400, {"error": "bad id"})
                with lock:
                    t = q.get(tid)
                return self._json(200, t) if t else self._json(404, {"error": "not found"})
            return self._json(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)
