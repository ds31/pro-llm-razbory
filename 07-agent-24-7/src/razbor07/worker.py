"""Воркер для docker compose: берёт задачу из очереди, исполняет агента, продлевает аренду, пишет трассу.

Время — «модельные» секунды: time.time() / TIME_SCALE. При TIME_SCALE=1 это обычный прод; при 0,02
минута работы проходит за 1,2 с — так короткий сценарий в docker compose идёт минуту, а не час.
Вместо фейковой модели в проде подставляется вызов SDK в `execute_call` (с таймаутом и max_retries).

SIGTERM: воркер доделывает текущую задачу и выходит (docker compose stop, деплой). kill -9: задача
остаётся в аренде, аренда истекает, задачу берёт другой воркер — письмо не уйдёт второй раз по ключу.
"""
from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from .agent import PROD, Call, Config, ModelError, Send, Sleep, Tool, agent_run
from .fakellm import Faults, FakeModel, Outcome, rng
from .mailer import SqliteMailGateway
from .queue import Queue, backoff
from .trace import Tracer


class Clock:
    def __init__(self, scale: float = 1.0):
        self.scale = scale

    def now(self) -> float:
        return time.time() / self.scale

    def sleep(self, model_seconds: float):
        time.sleep(max(model_seconds, 0.0) * self.scale)


class Worker:
    def __init__(self, db: str | Path, name: str, cfg: Config = PROD, faults: Faults | None = None, seed: int = 48,
                 clock: Clock | None = None, tracer: Tracer | None = None, alive_file: str | None = None,
                 chaos_kill_p: float = 0.0):
        self.db, self.name, self.cfg = str(db), name, cfg
        self.q = Queue(self.db)
        self.mail = SqliteMailGateway(self.db)
        self.model = FakeModel(faults or Faults(), seed)
        self.seed = seed
        self.clock = clock or Clock()
        self.tr = tracer or Tracer(keep=False)
        self.alive_file = alive_file
        self.chaos_kill_p = chaos_kill_p
        self.stopping = False
        self.n = 0
        self.boot = os.urandom(3).hex()   # id запуска: после рестарта контейнера pid и имя хоста те же

    # --- исполнение операций агента ------------------------------------------------------------
    def execute_call(self, op: Call, key: str, label: str) -> Outcome:
        out = self.model.call(self.clock.now(), key, label)
        if out.duration > op.timeout:
            self.clock.sleep(op.timeout)
            return Outcome("timeout", op.timeout, tokens_in=out.tokens_in)
        self.clock.sleep(out.duration)
        return out

    def run_task(self, key: str, owner: str, attempt: int):
        gen = agent_run(key, self.cfg, rng(self.seed, "sdk", key, owner))
        value = None
        while True:
            try:
                op = gen.send(value)
            except StopIteration:
                return
            value = None
            if isinstance(op, Call):
                t0 = self.clock.now()
                value = self.execute_call(op, key, f"{owner}.{op.step}.{op.try_no}")
                self.tr.emit(time.time(), "call", task=key, exec=owner, attempt=attempt, step=op.step,
                             try_no=op.try_no, kind=value.kind, ms=int((self.clock.now() - t0) * 1000),
                             tokens_in=value.tokens_in, tokens_out=value.tokens_out)
            elif isinstance(op, Send):
                self.clock.sleep(op.seconds)
                new = self.mail.send(self.clock.now(), op.task_key, op.idem_key)
                self.tr.emit(time.time(), "send" if new else "send_deduped", task=key, exec=owner,
                             attempt=attempt)
                if self.chaos_kill_p and rng(self.seed, "chaos", owner).random() < self.chaos_kill_p:
                    # хаос-тест: худшее окно — письмо ушло, задача не подтверждена
                    os.kill(os.getpid(), signal.SIGKILL)
            elif isinstance(op, (Tool, Sleep)):
                self.clock.sleep(op.seconds)

    # --- цикл --------------------------------------------------------------------------------
    def touch(self):
        if self.alive_file:
            Path(self.alive_file).touch()

    def _beat(self, tid: int, owner: str, stop: threading.Event):
        q = Queue(self.db)
        while not stop.wait(self.cfg.heartbeat * self.clock.scale):
            q.heartbeat(tid, owner, self.clock.now(), self.cfg.lease)
            self.touch()

    def once(self) -> bool:
        """Взять и исполнить одну задачу; False — очередь пуста."""
        self.n += 1
        owner = f"{self.name}#{self.boot}.{self.n}"
        t = self.q.claim(owner, self.clock.now(), self.cfg.lease, self.cfg.max_attempts)
        for tid, prev in self.q.reclaimed_dead:
            self.tr.emit(time.time(), "dead", task_id=tid, exec=prev, error="lease expired")
        self.q.reclaimed_dead.clear()
        if t is None:
            return False
        key = t.payload["key"]
        if t.reclaimed_from:
            self.tr.emit(time.time(), "lease_expired", task=key, task_id=t.id, exec=t.reclaimed_from)
        self.tr.emit(time.time(), "claimed", task=key, task_id=t.id, exec=owner, attempt=t.attempt,
                     worker=self.name)
        stop = threading.Event()
        hb = threading.Thread(target=self._beat, args=(t.id, owner, stop), daemon=True)
        hb.start()
        try:
            self.run_task(key, owner, t.attempt)
        except ModelError as e:
            delay = backoff(t.attempt, rng(self.seed, "backoff", owner), self.cfg.backoff_base, self.cfg.backoff_cap,
                            e.retry_after)
            res = self.q.fail(t.id, owner, self.clock.now(), f"{e.kind} на шаге {e.step}", e.retryable, delay,
                              self.cfg.max_attempts)
            ev = {"retry": "retry_scheduled", "dead": "dead", "lost": "lost_lease"}[res]
            self.tr.emit(time.time(), ev, task=key, task_id=t.id, exec=owner, attempt=t.attempt,
                         error=f"{e.kind} на шаге {e.step}", delay_s=round(delay, 1))
        else:
            ok = self.q.ack(t.id, owner, self.clock.now())
            self.tr.emit(time.time(), "done" if ok else "lost_lease", task=key, task_id=t.id, exec=owner,
                         attempt=t.attempt)
        finally:
            stop.set()
        return True

    def run(self, poll: float = 1.0, exit_when_idle: bool = False):
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stopping", True))
        self.tr.emit(time.time(), "worker_started", worker=self.name, pid=os.getpid())
        while not self.stopping:
            self.touch()
            if not self.once():
                if exit_when_idle:
                    break
                self.clock.sleep(poll)
        self.tr.emit(time.time(), "worker_stopped", worker=self.name)
