from razbor04.client import MeteredClient

from conftest import ScriptClient, reply, tool_use


def _call(client, **extra):
    return client.messages.create(model="m", max_tokens=10, messages=[], output_config={"effort": "medium"}, **extra)


def test_effort_kept_by_default():
    inner = ScriptClient([reply([])])
    _call(MeteredClient(inner))
    assert inner.calls[0]["output_config"] == {"effort": "medium"}


def test_effort_none_drops_param():
    inner = ScriptClient([reply([])])
    _call(MeteredClient(inner, effort=None))
    assert "output_config" not in inner.calls[0]


def test_effort_override():
    inner = ScriptClient([reply([])])
    _call(MeteredClient(inner, effort="low"))
    assert inner.calls[0]["output_config"] == {"effort": "low"}


def test_meter_records_each_call_and_billed_cost():
    inner = ScriptClient([reply([], tin=500, tout=50, cost=0.001, thinking=20, cache_read=100),
                          reply([], tin=700, tout=30)])
    c = MeteredClient(inner)
    _call(c)
    _call(c)
    calls = c.take()
    assert [x.input_tokens for x in calls] == [500, 700]
    assert calls[0].billed_usd == 0.001 and calls[1].billed_usd is None
    assert calls[0].thinking_tokens == 20 and calls[0].cache_read_tokens == 100
    assert c.take() == []  # take() очищает счётчик


def test_meter_survives_usage_without_extras():
    from types import SimpleNamespace as NS
    inner = ScriptClient([NS(content=[], stop_reason="end_turn", usage=NS(input_tokens=1, output_tokens=2))])
    c = MeteredClient(inner)
    _call(c)
    (x,) = c.take()
    assert (x.input_tokens, x.output_tokens, x.thinking_tokens, x.billed_usd) == (1, 2, 0, None)


def test_meter_reads_openrouter_extras_given_as_dicts():
    from types import SimpleNamespace as NS
    u = NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=None,
           output_tokens_details={"thinking_tokens": 3}, cost=2e-05)
    c = MeteredClient(ScriptClient([NS(content=[], stop_reason="end_turn", usage=u)]))
    _call(c)
    (x,) = c.take()
    assert (x.thinking_tokens, x.cache_read_tokens, x.billed_usd) == (3, 0, 2e-05)
