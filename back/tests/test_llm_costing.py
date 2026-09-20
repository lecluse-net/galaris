import pytest

from bridge.openrouter import PROFILE as OPENROUTER_PROFILE
from app.llm.costing import token_cost
from app.llm.llm_call_service import _cost


def test_openai_cached_tokens_are_discounted_without_double_counting():
    cost = token_cost(
        input_tokens=100,
        output_tokens=25,
        cache_read_tokens=40,
        input_rate=2.0,
        cached_input_rate=0.5,
        output_rate=4.0,
        input_includes_cache=True,
    )
    assert cost == pytest.approx((60 * 2.0 + 40 * 0.5 + 25 * 4.0) / 1_000_000)


def test_separate_cache_counters_are_added_for_pydantic_usage():
    cost = token_cost(
        input_tokens=60,
        output_tokens=25,
        cache_read_tokens=40,
        input_rate=2.0,
        cached_input_rate=0.5,
        output_rate=4.0,
        input_includes_cache=False,
    )
    assert cost == pytest.approx((60 * 2.0 + 40 * 0.5 + 25 * 4.0) / 1_000_000)


def test_missing_cached_rate_preserves_legacy_full_input_rate():
    cost = token_cost(
        input_tokens=100,
        output_tokens=0,
        cache_read_tokens=40,
        input_rate=2.0,
        cached_input_rate=None,
        output_rate=4.0,
        input_includes_cache=True,
    )
    assert cost == pytest.approx(100 * 2.0 / 1_000_000)


def test_proxy_cost_uses_provider_total_when_available():
    cost, estimated = _cost(
        {"cost": 0.123},
        {
            "input_tokens": 100,
            "output_tokens": 25,
            "cache_read_tokens": 40,
            "cache_write_tokens": 0,
        },
        2.0,
        0.5,
        4.0,
    )
    assert cost == 0.123
    assert estimated is False


def test_openrouter_cost_uses_routed_provider_charge():
    cost, estimated = _cost(
        {
            "cost": "0.456",
            "cost_details": {"upstream_inference_cost": 0.321},
        },
        {
            "input_tokens": 100,
            "output_tokens": 25,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        },
        2.0,
        None,
        4.0,
        OPENROUTER_PROFILE.code,
    )

    assert cost == pytest.approx(0.456)
    assert estimated is False


def test_openrouter_cost_falls_back_to_upstream_detail():
    cost, estimated = _cost(
        {"cost_details": {"upstream_inference_cost": "0.321"}},
        {
            "input_tokens": 100,
            "output_tokens": 25,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        },
        2.0,
        None,
        4.0,
        OPENROUTER_PROFILE.code,
    )

    assert cost == pytest.approx(0.321)
    assert estimated is False
