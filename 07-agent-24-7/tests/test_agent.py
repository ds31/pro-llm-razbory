import json
import random

import pytest

from razbor07.agent import NAIVE, PROD, QUEUE, Call, ModelError, Send, Sleep, agent_run
from razbor07.fakellm import Outcome
from razbor07.mailer import MailGateway, SqliteMailGateway
from razbor07.trace import Tracer, cost_usd

OK = Outcome("ok", 3.0, tokens_in=1000, tokens_out=200)


def run_all(gen, answers):
    """Прогнать генератор агента, отвечая на Call по списку answers; вернуть список операций."""
    ops, value, answers = [], None, list(answers)
    try:
        while True:
            op = gen.send(value)
            ops.append(op)
            value = answers.pop(0) if isinstance(op, Call) else None
    except StopIteration:
        return ops


def test_happy_path_order_plan_tool_answer_send_finish():
    ops = run_all(agent_run("store-01:q1", PROD, random.Random(1)), [OK, OK, OK])
    kinds = [type(o).__name__ for o in ops]
    assert kinds == ["Call", "Tool", "Call", "Send", "Call"]
    assert [o.step for o in ops if isinstance(o, Call)] == ["plan", "answer", "finish"]
    assert ops[3].idem_key == "store-01:q1:reply"
    assert all(o.timeout == 30 for o in ops if isinstance(o, Call))


def test_queue_config_sends_without_key_and_naive_waits_ten_minutes():
    ops = run_all(agent_run("k", QUEUE, random.Random(1)), [OK, OK, OK])
    assert [o for o in ops if isinstance(o, Send)][0].idem_key is None
    ops = run_all(agent_run("k", NAIVE, random.Random(1)), [OK, OK, OK])
    assert all(o.timeout == 600 for o in ops if isinstance(o, Call))


def test_sdk_style_retry_honors_retry_after_then_succeeds():
    rl = Outcome("rate_limited", 0.2, retry_after=12.5)
    ops = run_all(agent_run("k", NAIVE, random.Random(1)), [rl, OK, OK, OK])
    assert isinstance(ops[1], Sleep) and ops[1].seconds == 12.5
    assert [o.try_no for o in ops if isinstance(o, Call)][:2] == [0, 1]


def test_sdk_backoff_without_retry_after_is_short():
    over = Outcome("overloaded", 0.5)
    ops = run_all(agent_run("k", NAIVE, random.Random(1)), [over, over, OK, OK, OK])
    sleeps = [o.seconds for o in ops if isinstance(o, Sleep)]
    assert 0.375 <= sleeps[0] <= 0.5 and 0.75 <= sleeps[1] <= 1.0


def test_gives_up_after_sdk_retries():
    drop = Outcome("drop", 1.0)
    with pytest.raises(ModelError) as e:
        run_all(agent_run("k", PROD, random.Random(1)), [OK, OK, drop, drop, drop])
    assert e.value.kind == "drop" and e.value.retryable and e.value.step == "finish"


def test_bad_request_is_not_retried():
    bad = Outcome("bad_request", 0.3)
    with pytest.raises(ModelError) as e:
        run_all(agent_run("k", PROD, random.Random(1)), [bad])
    assert not e.value.retryable


def test_gateway_dedups_only_with_key():
    g = MailGateway()
    assert g.send(1.0, "k", None) and g.send(2.0, "k", None)
    assert g.send(3.0, "m", "m:reply") and not g.send(4.0, "m", "m:reply")
    assert g.deliveries == {"k": [1.0, 2.0], "m": [3.0]}
    assert g.deduped == 1


def test_sqlite_gateway(tmp_path):
    g = SqliteMailGateway(tmp_path / "q.db")
    assert g.send(1.0, "m", "m:reply") and not g.send(2.0, "m", "m:reply")
    assert g.send(3.0, "k", None) and g.send(4.0, "k", None)
    assert g.counts() == {"k": 2, "m": 1}


def test_tracer_writes_jsonl_with_cost(tmp_path):
    p = tmp_path / "trace.jsonl"
    tr = Tracer(p)
    tr.emit(1.5, "call_ok", task="k", attempt=1, step="plan", ms=3000, tokens_in=1000, tokens_out=200)
    line = json.loads(p.read_text().splitlines()[0])
    assert line["event"] == "call_ok" and line["task"] == "k"
    assert line["cost_usd"] == pytest.approx(cost_usd(1000, 200))
    assert tr.events[0]["t"] == 1.5
