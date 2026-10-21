import pytest

from razbor04.prices import PRICES, UnknownModel, list_cost, price, slug


def test_task_models_are_priced():
    for m in ["anthropic/claude-opus-5.5", "anthropic/claude-sonnet-5.5", "anthropic/claude-haiku-5.5",
              "deepseek/deepseek-v4.1-flash", "openai/gpt-5.6-luna", "z-ai/glm-5.3"]:
        pin, pout = price(m)
        assert 0 < pin <= pout


def test_list_cost_per_million():
    pin, pout = PRICES["anthropic/claude-sonnet-5.5"]
    assert list_cost("anthropic/claude-sonnet-5.5", 1_000_000, 100_000) == pytest.approx(pin + pout / 10)


def test_unknown_model_is_explicit_error():
    with pytest.raises(UnknownModel, match="add-model"):
        price("acme/unknown-1")


def test_slug_is_file_safe():
    assert slug("anthropic/claude-haiku-5.5") == "anthropic__claude-haiku-5.5"
