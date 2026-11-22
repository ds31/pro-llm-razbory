"""Симулятор «ночи» с виртуальными часами: 1 000 задач, сбои модели, kill -9, клиент, который переспрашивает.

Дискретные события: часы прыгают от события к событию, поэтому сутки работы считаются за секунды
и детерминированно по seed. Конфигурация «наивная» исполняет агента прямо в обработчике API
(один процесс, поток на запрос); «очередь» и «прод» — через настоящую очередь `queue.Queue`
(SQLite в памяти) и воркеры. Агент один и тот же (`agent.agent_run`).

Клиент — бот магазина: шлёт вопрос, ждёт ответа API не дольше client_timeout и при ошибке,
обрыве или тишине переспрашивает один раз (как повторная доставка вебхука).
"""
from __future__ import annotations

import heapq
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from .agent import Call, Config, ModelError, Send, Sleep, Tool, agent_run
from .fakellm import Faults, FakeModel, Outcome, rng
from .mailer import MailGateway
from .queue import Queue, backoff
from .trace import START, TERMINAL, Tracer

QUESTIONS = (
    "Сколько продали молочки вчера и как к прошлой неделе?",
    "Почему упал средний чек в субботу?",
    "Какие товары закончатся до четверга?",
    "Сводка по выручке магазина за неделю",
    "Сколько списали фруктов за месяц?",
    "Какие акции дали прирост в октябре?",
)


@dataclass(frozen=True)
class Night:
    tasks: int = 1000
    hours: float = 4.0               # окно поступления задач
    peak_share: float = 0.3          # доля задач в утреннем пике
    peak_at: float = 3600.0          # пик через час после начала окна
    peak_len: float = 600.0          # 10 минут
    stores: int = 60
    crash_every: float = 1800.0      # среднее время между kill -9 на процесс агента, с; 0 — без падений
    restart_delay: float = 5.0       # restart: unless-stopped поднимает процесс
    p_lost_response: float = 0.01    # ответ API клиенту потерялся в сети
    client_timeout: float = 60.0
    client_resend_delay: float = 10.0
    poll: float = 1.0                # воркер без задач спрашивает очередь раз в секунду
    faults: Faults = field(default_factory=Faults)
    horizon: float = 48 * 3600.0


@dataclass(frozen=True)
class TaskSpec:
    key: str
    store: int
    question: str
    arrival: float


def workload(night: Night, seed: int) -> list[TaskSpec]:
    r = rng(seed, "workload")
    n_peak = round(night.tasks * night.peak_share)
    times = [r.uniform(night.peak_at, night.peak_at + night.peak_len) for _ in range(n_peak)]
    times += [r.uniform(0.0, night.hours * 3600.0) for _ in range(night.tasks - n_peak)]
    times.sort()
    out = []
    for i, t in enumerate(times):
        store = r.randint(1, night.stores)
        out.append(TaskSpec(f"store-{store:02d}/q-{i + 1:04d}", store, r.choice(QUESTIONS), round(t, 3)))
    return out


def crash_times(night: Night, seed: int, proc: str) -> list[float]:
    if not night.crash_every:
        return []
    r, t, out = rng(seed, "crash", proc), 0.0, []
    end = night.hours * 3600.0 + 6 * 3600.0
    while True:
        t += r.expovariate(1.0 / night.crash_every)
        if t > end:
            return out
        out.append(round(t, 3))


@dataclass
class Proc:
    name: str
    epoch: int = 0
    down: bool = False
    busy: object = None
    started: int = 0


@dataclass(eq=False)
class Exec:
    proc: Proc
    epoch: int
    key: str
    exec_id: str
    attempt: int
    gen: object
    on_done: object
    on_error: object
    task_id: int | None = None
    n: int = 0                       # номер запроса клиента (наивная)
    waiting: bool = False            # клиент ещё ждёт ответа (наивная)
    no: int = 0                      # номер исполнения этой задачи: метка вызовов модели


@dataclass
class SimResult:
    config: str
    seed: int
    tasks: list[TaskSpec]
    events: list[dict]
    metrics: dict


class _Run:
    def __init__(self, cfg: Config, night: Night, seed: int):
        self.cfg, self.night, self.seed = cfg, night, seed
        self.heap: list = []
        self.seq = 0
        self.now = 0.0
        self.stop = False
        self.model = FakeModel(night.faults, seed)
        self.mail = MailGateway()
        self.tr = Tracer(keep=True)
        self.tasks = workload(night, seed)
        self.spec = {t.key: t for t in self.tasks}
        self.execs = defaultdict(int)            # сколько исполнений начато по задаче
        self.c = defaultdict(int)                # счётчики
        self.tokens_in = self.tokens_out = 0
        self.pending_client = 0
        self.arrived = 0
        self.inflight: dict = {}                 # dict, а не set: порядок вставки детерминирован

    # --- часы -----------------------------------------------------------------------------
    def at(self, t: float, fn, *args):
        heapq.heappush(self.heap, (t, self.seq, fn, args))
        self.seq += 1

    def loop(self):
        while self.heap and not self.stop:
            t, _, fn, args = heapq.heappop(self.heap)
            if t > self.night.horizon:
                break
            self.now = t
            fn(*args)

    def emit(self, event: str, **kw):
        self.tr.emit(self.now, event, **kw)

    # --- исполнение агента -------------------------------------------------------------------
    def start_exec(self, proc: Proc, key: str, exec_id: str, attempt: int, on_done, on_error, **kw) -> Exec:
        self.execs[key] += 1
        no = self.execs[key]
        gen = agent_run(key, self.cfg, rng(self.seed, "sdk", key, no))
        return Exec(proc, proc.epoch, key, exec_id, attempt, gen, on_done, on_error, no=no, **kw)

    def alive(self, ex: Exec) -> bool:
        return ex.proc.epoch == ex.epoch

    def step(self, ex: Exec, value=None):
        if not self.alive(ex):
            return
        try:
            op = ex.gen.send(value)
        except StopIteration:
            ex.on_done(ex)
            return
        except ModelError as e:
            ex.on_error(ex, e)
            return
        if isinstance(op, Call):
            out = self.model.call(self.now, ex.key, f"{ex.no}.{op.step}.{op.try_no}")
            if out.kind in ("ok", "drop", "bad_request", "hang"):
                self.c["calls_billed"] += 1
                self.tokens_in += out.tokens_in
                self.tokens_out += out.tokens_out
            if out.duration > op.timeout:
                res, dur = Outcome("timeout", op.timeout, tokens_in=out.tokens_in), op.timeout
            else:
                res, dur = out, out.duration
            self.at(self.now + dur, self.call_done, ex, op, res, dur)
        elif isinstance(op, Send):
            self.at(self.now + op.seconds, self.send_done, ex, op)
        elif isinstance(op, (Tool, Sleep)):
            self.at(self.now + op.seconds, self.step, ex, None)

    def call_done(self, ex: Exec, op: Call, res: Outcome, dur: float):
        if not self.alive(ex):
            return
        self.c[res.kind] += 1
        self.emit("call", task=ex.key, exec=ex.exec_id, attempt=ex.attempt, step=op.step, try_no=op.try_no,
                  kind=res.kind, ms=int(dur * 1000), tokens_in=res.tokens_in, tokens_out=res.tokens_out)
        self.step(ex, res)

    def send_done(self, ex: Exec, op: Send):
        if not self.alive(ex):
            return
        new = self.mail.send(self.now, op.task_key, op.idem_key)
        self.emit("send" if new else "send_deduped", task=ex.key, exec=ex.exec_id, attempt=ex.attempt)
        self.step(ex, None)

    def crash(self, proc: Proc):
        if proc.down:
            return
        proc.epoch += 1
        proc.down = True
        proc.busy = None
        self.c["crashes"] += 1
        self.at(self.now + self.night.restart_delay, self.restart, proc)
        self.on_crash(proc)

    def on_crash(self, proc: Proc):
        pass

    def restart(self, proc: Proc):
        proc.down = False
        self.on_restart(proc)

    def on_restart(self, proc: Proc):
        pass

    def lost_response(self, key: str, n: int) -> bool:
        return rng(self.seed, "lostresp", key, n).random() < self.night.p_lost_response

    # --- итог ------------------------------------------------------------------------------
    def metrics(self, dead_keys: set[str]) -> dict:
        n = len(self.tasks)
        deliv = self.mail.deliveries
        delivered = [k for k in self.spec if deliv.get(k)]
        lost = [k for k in self.spec if not deliv.get(k) and k not in dead_keys]
        lat = sorted(min(deliv[k]) - self.spec[k].arrival for k in delivered)
        q = statistics.quantiles(lat, n=100, method="inclusive") if len(lat) >= 2 else [0.0] * 99
        # трасса: у каждой начатой попытки есть событие, которым она кончилась
        started, ended, keys_of = set(), set(), defaultdict(set)
        for e in self.tr.events:
            if "exec" not in e:
                continue
            keys_of[e["task"]].add(e["exec"])
            if e["event"] in START:
                started.add(e["exec"])
            if e["event"] in TERMINAL:
                ended.add(e["exec"])
        complete = sum(1 for k in self.spec if keys_of[k] and all(x in ended for x in keys_of[k] if x in started))
        no_trace_lost = sum(1 for k in lost if not all(x in ended for x in keys_of[k] if x in started))
        dup = [k for k in delivered if len(deliv[k]) > 1]
        dead_undelivered = dead_keys - set(delivered)
        return {
            "tasks": n,
            "delivered": len(delivered),
            "lost": len(lost),
            "lost_without_trace": no_trace_lost,
            "dead": len(dead_undelivered),
            "dead_exhausted": sum(1 for k in dead_undelivered if not self.model.is_poison(k)),
            "dup_tasks": len(dup),
            "extra_messages": sum(len(deliv[k]) - 1 for k in dup),
            "p50": round(q[49], 1) if lat else None,
            "p95": round(q[94], 1) if lat else None,
            "p99": round(q[98], 1) if lat else None,
            "max": round(lat[-1], 1) if lat else None,
            "trace_complete": complete,
            "calls_billed": self.c["calls_billed"],
            "calls_per_delivered": round(self.c["calls_billed"] / max(len(delivered), 1), 2),
            "rejected_429": self.model.rejected,
            "timeouts": self.c["timeout"],
            "drops": self.c["drop"],
            "overloaded": self.c["overloaded"],
            "crashes": self.c["crashes"],
            "executions": sum(self.execs.values()),
            "dedup_enqueue": self.c["dedup_enqueue"],
            "dedup_send": self.mail.deduped,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "finished_at": round(self.now, 1),
        }


class _NaiveRun(_Run):
    """Обработчик API зовёт агента сам. Процесс один, на запрос — поток; kill -9 убивает все запросы."""

    def run(self) -> SimResult:
        self.api = Proc("api")
        self.req_no = 0
        self.waiters: dict = {}
        for t in crash_times(self.night, self.seed, "api"):
            self.at(t, self.crash, self.api)
        for spec in self.tasks:
            self.at(spec.arrival, self.client_send, spec, 0)
        # падения идут и после того, как все задачи завершены: остановить, когда больше нечего ждать
        self.at(0.0, self.watch)
        self.loop()
        return SimResult(self.cfg.name, self.seed, self.tasks, self.tr.events, self.metrics(set()))

    def watch(self):
        if self.arrived == len(self.tasks) and not self.inflight and not self.waiters and self.pending_client == 0:
            self.stop = True
            return
        self.at(self.now + 5.0, self.watch)

    def client_send(self, spec: TaskSpec, n: int):
        if n == 0:
            self.arrived += 1
        else:
            self.pending_client -= 1
        if self.api.down:  # connection refused
            self.emit("refused", task=spec.key, n=n)
            self.client_retry(spec, n, self.night.client_resend_delay)
            return
        self.req_no += 1
        ex = self.start_exec(self.api, spec.key, f"api#{self.req_no}", n + 1, self.req_done, self.req_error, n=n)
        self.wait(ex, True)
        self.inflight[ex] = None
        self.emit("request_start", task=spec.key, exec=ex.exec_id, attempt=ex.attempt)
        self.at(self.now + self.night.client_timeout, self.client_timeout, ex)
        self.step(ex)

    def client_retry(self, spec: TaskSpec, n: int, delay: float):
        if n == 0:
            self.pending_client += 1
            self.at(self.now + delay, self.client_send, spec, 1)

    def wait(self, ex: Exec, on: bool):
        ex.waiting = on
        if on:
            self.waiters[ex] = None
        else:
            self.waiters.pop(ex, None)

    def client_timeout(self, ex: Exec):
        if ex.waiting:
            self.wait(ex, False)
            self.emit("client_timeout", task=ex.key, exec=ex.exec_id)
            self.client_retry(self.spec[ex.key], ex.n, 0.0)

    def req_done(self, ex: Exec):
        self.inflight.pop(ex, None)
        self.emit("request_done", task=ex.key, exec=ex.exec_id, attempt=ex.attempt)
        if ex.waiting and not self.lost_response(ex.key, ex.n):
            self.wait(ex, False)  # потерянный ответ: клиент ждёт до таймаута и переспрашивает

    def req_error(self, ex: Exec, e: ModelError):
        self.inflight.pop(ex, None)
        self.emit("request_error", task=ex.key, exec=ex.exec_id, attempt=ex.attempt, error=e.kind, step=e.step)
        if ex.waiting:
            self.wait(ex, False)
            self.client_retry(self.spec[ex.key], ex.n, self.night.client_resend_delay)

    def on_crash(self, proc: Proc):
        # kill -9: обработчики не успевают ничего записать; клиенты видят обрыв соединения
        for ex in list(self.inflight):
            self.inflight.pop(ex, None)
            if ex.waiting:
                self.wait(ex, False)
                self.client_retry(self.spec[ex.key], ex.n, self.night.client_resend_delay)


class _QueueRun(_Run):
    """API ставит задачу в очередь и сразу отвечает 202; воркеры берут задачи с арендой."""

    def run(self) -> SimResult:
        self.q = Queue(":memory:")
        self.key_of: dict[int, str] = {}
        self.workers = [Proc(f"w{i + 1}") for i in range(self.cfg.workers)]
        for w in self.workers:
            for t in crash_times(self.night, self.seed, w.name):
                self.at(t, self.crash, w)
            self.at(0.0, self.poll, w, w.epoch)
        for spec in self.tasks:
            self.at(spec.arrival, self.client_send, spec, 0)
        self.loop()
        dead = {self.key_of[d["id"]] for d in self.q.dead_letters()}
        m = self.metrics(dead)
        m["dead_letter_rows"] = len(self.q.dead_letters())
        return SimResult(self.cfg.name, self.seed, self.tasks, self.tr.events, m)

    def client_send(self, spec: TaskSpec, n: int):
        if n == 0:
            self.arrived += 1
        else:
            self.pending_client -= 1
        payload = {"key": spec.key, "store": spec.store, "question": spec.question}
        tid, created = self.q.enqueue(payload, self.now, key=spec.key if self.cfg.idempotent else None)
        self.key_of[tid] = spec.key
        if not created:
            self.c["dedup_enqueue"] += 1
        self.emit("received", task=spec.key, task_id=tid, n=n, duplicate=not created)
        if self.lost_response(spec.key, n) and n == 0:
            self.pending_client += 1
            self.at(self.now + self.night.client_timeout, self.client_send, spec, 1)

    def finished(self) -> bool:
        if self.arrived < len(self.tasks) or self.pending_client:
            return False
        counts = self.q.counts()
        return not counts.get("queued") and not counts.get("leased")

    def poll(self, w: Proc, epoch: int):
        if w.epoch != epoch or w.down or w.busy is not None:
            return
        w.started += 1
        owner = f"{w.name}#{w.started}"
        t = self.q.claim(owner, self.now, self.cfg.lease, self.cfg.max_attempts)
        for tid, prev in self.q.reclaimed_dead:
            key = self.key_of[tid]
            self.emit("lease_expired", task=key, task_id=tid, exec=prev)
            self.emit("dead", task=key, task_id=tid, error="lease expired")
        self.q.reclaimed_dead.clear()
        if t is None:
            if self.finished():
                self.stop = True
                return
            self.at(self.now + self.night.poll, self.poll, w, epoch)
            return
        key = self.key_of[t.id]
        if t.reclaimed_from:
            self.emit("lease_expired", task=key, task_id=t.id, exec=t.reclaimed_from)
        ex = self.start_exec(w, key, owner, t.attempt, self.done, self.error, task_id=t.id)
        w.busy = ex
        self.emit("claimed", task=key, task_id=t.id, exec=owner, attempt=t.attempt, worker=w.name)
        self.at(self.now + self.cfg.heartbeat, self.beat, ex)
        self.step(ex)

    def beat(self, ex: Exec):
        if self.alive(ex) and ex.proc.busy is ex:
            self.q.heartbeat(ex.task_id, ex.exec_id, self.now, self.cfg.lease)
            self.at(self.now + self.cfg.heartbeat, self.beat, ex)

    def release(self, ex: Exec):
        ex.proc.busy = None
        self.poll(ex.proc, ex.proc.epoch)

    def done(self, ex: Exec):
        ok = self.q.ack(ex.task_id, ex.exec_id, self.now)
        self.emit("done" if ok else "lost_lease", task=ex.key, task_id=ex.task_id, exec=ex.exec_id,
                  attempt=ex.attempt)
        self.release(ex)

    def error(self, ex: Exec, e: ModelError):
        r = rng(self.seed, "backoff", ex.key, ex.exec_id)
        delay = backoff(ex.attempt, r, self.cfg.backoff_base, self.cfg.backoff_cap, e.retry_after)
        res = self.q.fail(ex.task_id, ex.exec_id, self.now, f"{e.kind} на шаге {e.step}", e.retryable, delay,
                          self.cfg.max_attempts)
        ev = {"retry": "retry_scheduled", "dead": "dead", "lost": "lost_lease"}[res]
        extra = {"delay_s": round(delay, 1)} if res == "retry" else {}
        self.emit(ev, task=ex.key, task_id=ex.task_id, exec=ex.exec_id, attempt=ex.attempt,
                  error=f"{e.kind} на шаге {e.step}", **extra)
        self.release(ex)

    def on_restart(self, proc: Proc):
        self.emit("worker_started", worker=proc.name)
        self.poll(proc, proc.epoch)


def simulate(cfg: Config, night: Night, seed: int) -> SimResult:
    run = (_QueueRun if cfg.queue else _NaiveRun)(cfg, night, seed)
    return run.run()
