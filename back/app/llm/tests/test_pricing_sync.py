"""Synthetic HTTP/DB journeys for nightly prices and immutable historical costs."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import llm_call_service, llm_service, pricing_sync
from app.llm.models import LLMCall
from app.llm.provider_models import LLM, LLMProvider
from app.llm.provider_schemas import LLMCreate, LLMResponse, LLMUpdate
from bridge.models_dev import service as models_dev


async def seed(db: AsyncSession, **values) -> LLM:
    # The isolated installation includes default resources; this journey owns only its fixture.
    await db.execute(update(LLM).values(pricing_auto_update=False))
    provider = LLMProvider(name="Synthetic pricing", provider_type="openai_compatible",
                           base_url="https://openrouter.ai/api/v1", is_active=True)
    db.add(provider)
    await db.flush()
    return await llm_service.create_llm(LLMCreate(
        llm_provider_id=provider.id, code="synthetic-price", llm_name="vendor/synthetic",
        label="Synthetic model", cost_per_input_token=9, cost_per_output_token=12,
        cost_per_cached_input_token=2, pricing={"input": 9, "output": 12, "cached_input": 2, "unit": "preserved"},
        **values,
    ))


@pytest.fixture
def upstream(monkeypatch):
    state = {"catalog": {"input": 1, "output": 4, "cache_read": .1},
             "live": {"prompt": "0.000002", "completion": "0.000006"}, "fail": False,
             "fail_live": False, "fail_catalog": False}
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if state["fail"] or (state["fail_catalog"] and request.url.host == "models.dev") or (
            state["fail_live"] and request.url.host != "models.dev"
        ):
            return httpx.Response(503)
        if request.url.host == "models.dev":
            return httpx.Response(200, json={"openrouter": {"models": {
                "vendor/synthetic": {"cost": state["catalog"]},
                "synthetic": {"cost": {"input": 999, "output": 999}},
            }}})
        return httpx.Response(200, json={"data": [{"id": "vendor/synthetic", "pricing": state["live"]}]})

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    models_dev.clear_cache()
    yield state, requests
    models_dev.clear_cache()


@pytest.mark.asyncio
async def test_nightly_refresh_provider_priority_cache_fallback_and_historical_costs(db, upstream):
    llm = await seed(db)
    old = LLMCall(llm_id=llm.id, status="completed", cost=.75, inference_cost=.75,
                  usage={"_galaris_cost": {"input_rate": 9, "output_rate": 12}})
    db.add(old)
    await db.commit()
    await pricing_sync.refresh_pricing()
    await db.refresh(llm)
    await db.refresh(old)
    assert (llm.cost_per_input_token, llm.cost_per_output_token, llm.cost_per_cached_input_token) == (2, 6, .1)
    assert llm.pricing == {"input": 2, "output": 6, "cached_input": .1, "unit": "preserved"}
    assert llm.pricing_provenance["input"]["source"] == "provider"
    assert llm.pricing_provenance["cached_input"]["source"] == "models.dev"
    assert llm.pricing_refresh_error is None
    response = LLMResponse.model_validate(llm)
    assert response.pricing_auto_update and response.pricing_updated_at is not None
    assert old.cost == .75 and old.usage["_galaris_cost"]["input_rate"] == 9
    count = len(upstream[1])
    await pricing_sync.refresh_pricing()
    assert len(upstream[1]) == count  # A restart/second poll does not repeat this night's work.
    new_call = LLMCall(llm_id=llm.id)
    db.add(new_call)
    await db.commit()
    await llm_call_service.finalize_call(new_call.id, trace={"usage": {
        "prompt_tokens": 1000, "completion_tokens": 200,
        "prompt_tokens_details": {"cached_tokens": 400},
    }}, input_rate=llm.cost_per_input_token, cached_input_rate=llm.cost_per_cached_input_token,
        output_rate=llm.cost_per_output_token)
    await db.refresh(new_call)
    assert new_call.cost == pytest.approx(.00244)
    assert new_call.usage["_galaris_cost"]["cached_input_rate"] == .1


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_success", [False, True])
async def test_failures_preserve_prices_and_dates_and_retry_after_cooldown(db, upstream, previous_success):
    llm = await seed(db)
    previous = datetime.now(timezone.utc) - timedelta(days=2) if previous_success else None
    llm.pricing_updated_at = previous
    await db.commit()
    upstream[0]["fail"] = True
    # A discovery cache from yesterday must never masquerade as a successful refresh.
    models_dev._cache = {"openrouter": {"models": {"vendor/synthetic": {"cost": {"input": 999}}}}}
    models_dev._cache_loaded_at = 1
    await pricing_sync.refresh_pricing()
    await db.refresh(llm)
    assert llm.pricing_updated_at == previous
    assert llm.pricing_refresh_error == "unavailable"
    assert llm.cost_per_input_token == 9
    count = len(upstream[1])
    await pricing_sync.refresh_pricing()
    assert len(upstream[1]) == count
    llm.pricing_last_attempt_at -= timedelta(minutes=31)
    await db.commit()
    upstream[0]["fail"] = False
    await pricing_sync.refresh_pricing()
    await db.refresh(llm)
    assert llm.cost_per_input_token == 2 and llm.pricing_refresh_error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_source", ["fail_live", "fail_catalog"])
async def test_one_failed_source_does_not_prevent_other_prices(db, upstream, failed_source):
    llm = await seed(db)
    upstream[0][failed_source] = True
    await pricing_sync.refresh_pricing()
    await db.refresh(llm)
    assert llm.cost_per_input_token == (1 if failed_source == "fail_live" else 2)
    assert llm.cost_per_cached_input_token == (.1 if failed_source == "fail_live" else 2)
    assert llm.pricing_updated_at is not None and llm.pricing_refresh_error is None


@pytest.mark.asyncio
async def test_zero_is_a_price_missing_invalid_and_wrong_models_do_not_erase_rates(db, upstream):
    llm = await seed(db)
    upstream[0]["catalog"] = {}
    upstream[0]["live"] = {"prompt": "0", "completion": "NaN", "input_cache_read": "-1"}
    await pricing_sync.refresh_pricing()
    await db.refresh(llm)
    assert llm.cost_per_input_token == 0
    assert llm.cost_per_output_token == 12 and llm.cost_per_cached_input_token == 2
    assert set(llm.pricing_provenance) == {"input"}
    # The similarly named catalog entry must not be guessed when the exact ID is absent.
    connection = pricing_sync.provider_connection(await db.get(LLMProvider, llm.llm_provider_id), None)
    assert await models_dev.ModelsDevMetadata().get_model_pricing(connection, ("other/synthetic",)) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [None, "", False])
async def test_null_or_invalid_provider_price_is_never_imported_as_free(db, upstream, missing):
    llm = await seed(db)
    upstream[0]["catalog"] = {}
    upstream[0]["live"] = {"prompt": missing, "completion": "0.000006"}
    await pricing_sync.refresh_pricing()
    await db.refresh(llm)
    assert llm.cost_per_input_token == 9
    assert llm.cost_per_output_token == 6


@pytest.mark.asyncio
async def test_manual_prices_and_inactive_or_deleted_resources_are_excluded(db, upstream):
    llm = await seed(db, pricing_auto_update=False)
    await pricing_sync.refresh_pricing()
    assert upstream[1] == []
    await llm_service.update_llm(llm.id, LLMUpdate(cost_per_input_token=7, pricing_auto_update=False))
    assert llm.pricing["input"] == 7
    await llm_service.update_llm(llm.id, LLMUpdate(pricing_auto_update=True))
    provider = await db.get(LLMProvider, llm.llm_provider_id)
    provider.is_active = False
    await db.commit()
    await pricing_sync.refresh_pricing()
    assert upstream[1] == []
    provider.is_active = True
    llm.soft_delete()
    await db.commit()
    await pricing_sync.refresh_pricing()
    assert upstream[1] == []


@pytest.mark.asyncio
async def test_claims_survive_restart_and_late_responses_cannot_overwrite_manual_edits(db, upstream):
    llm = await seed(db)
    now = datetime.now(timezone.utc)
    claimed = await pricing_sync._claim(now)
    assert len(claimed) == 1
    assert await pricing_sync._claim(now) == []
    prices, sources = await pricing_sync._fetch(claimed[0])
    await llm_service.update_llm(llm.id, LLMUpdate(pricing_auto_update=False, cost_per_input_token=7))
    await pricing_sync._apply(claimed[0], prices, sources, now)
    await db.refresh(llm)
    assert llm.cost_per_input_token == 7 and llm.pricing_updated_at is None


@pytest.mark.parametrize(("reference", "expected"), [
    ("2026-10-24T00:30:00+00:00", "2026-10-23T01:00:00+00:00"),
    ("2026-10-24T01:00:00+00:00", "2026-10-24T01:00:00+00:00"),
    ("2026-10-25T01:30:00+00:00", "2026-10-24T01:00:00+00:00"),
    ("2026-10-25T02:00:00+00:00", "2026-10-25T02:00:00+00:00"),
    ("2026-03-29T01:00:00+00:00", "2026-03-29T01:00:00+00:00"),
])
def test_nightly_boundary_uses_local_time_and_daylight_saving(monkeypatch, reference, expected):
    monkeypatch.setenv("TZ", "Europe/Paris")
    assert pricing_sync.nightly_boundary(datetime.fromisoformat(reference)) == datetime.fromisoformat(expected)
