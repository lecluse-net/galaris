"""Provider-neutral, revisioned execution configuration and capability negotiation."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from pydantic import BaseModel, ConfigDict, Field

from app.agent import (
    HarnessCapability, HarnessCapabilityDescriptor, HarnessExecutionPolicy, driver_capabilities,
    list_driver_specs, negotiate_capabilities, DriverPipelinePolicy,
)
from core.database import get_db

from .models import HarnessExecutionConfiguration
from .registry import all_providers


async def configured_provider_capabilities(provider_code: str) -> frozenset[HarnessCapability]:
    """Management actions use the same policy as execution, including at dispatch time."""
    from .registry import get_provider

    provider = get_provider(provider_code)
    policy, _ = await read_policy(provider_code)
    return negotiate_capabilities(provider.capabilities(), policy=policy).effective


class HarnessConfigurationConflict(RuntimeError):
    pass


class HarnessConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    policy: HarnessExecutionPolicy


class HarnessConfigurationRead(BaseModel):
    provider_code: str
    label: str
    revision: int
    descriptor: HarnessCapabilityDescriptor
    pipeline_policy: DriverPipelinePolicy


def _declarations() -> dict[str, tuple[str, frozenset[HarnessCapability], DriverPipelinePolicy]]:
    specs = {spec.code: spec for spec in list_driver_specs()}
    declarations = {code: (spec.label_key, driver_capabilities(spec), spec.pipeline_policy) for code, spec in specs.items()}
    for provider in all_providers():
        spec = specs[provider.driver_code]
        declarations[provider.code] = (
            provider.label, driver_capabilities(spec) | provider.capabilities(), provider.pipeline_policy,
        )
    return declarations


async def read_policy(provider_code: str) -> tuple[HarnessExecutionPolicy, int]:
    row = await get_db().scalar(select(HarnessExecutionConfiguration).where(
        HarnessExecutionConfiguration.provider_code == provider_code,
    ))
    if row is None:
        return HarnessExecutionPolicy(), 0
    return HarnessExecutionPolicy.model_validate(row.policy), row.revision


async def describe_configuration(provider_code: str) -> HarnessConfigurationRead:
    declarations = _declarations()
    if provider_code not in declarations:
        raise LookupError(f"Unknown Harness provider: {provider_code!r}.")
    label, capabilities, pipeline_policy = declarations[provider_code]
    policy, revision = await read_policy(provider_code)
    return HarnessConfigurationRead(
        provider_code=provider_code, label=label, revision=revision,
        descriptor=negotiate_capabilities(capabilities, policy=policy, revision=revision),
        pipeline_policy=pipeline_policy,
    )


async def list_configurations() -> list[HarnessConfigurationRead]:
    return [await describe_configuration(code) for code in _declarations()]


async def update_configuration(
    provider_code: str, update: HarnessConfigurationUpdate,
) -> HarnessConfigurationRead:
    declarations = _declarations()
    if provider_code not in declarations:
        raise LookupError(f"Unknown Harness provider: {provider_code!r}.")
    _, capabilities, _ = declarations[provider_code]
    unknown = update.policy.disabled_capabilities - capabilities
    if unknown:
        raise ValueError(f"Capabilities not implemented by this Harness: {sorted(unknown)}")
    db = get_db()
    inserted = await db.scalar(insert(HarnessExecutionConfiguration).values(
        provider_code=provider_code, revision=1, policy=update.policy.model_dump(mode="json"),
    ).on_conflict_do_nothing(index_elements=[HarnessExecutionConfiguration.provider_code])
        .returning(HarnessExecutionConfiguration.id))
    row = await db.scalar(select(HarnessExecutionConfiguration).where(
        HarnessExecutionConfiguration.provider_code == provider_code,
    ).with_for_update().execution_options(populate_existing=True))
    assert row is not None
    expected = 0 if inserted is not None else row.revision
    if update.expected_revision != expected:
        raise HarnessConfigurationConflict("The Harness configuration changed; reload it before saving.")
    if inserted is None:
        row.revision += 1
        row.policy = update.policy.model_dump(mode="json")
    await db.commit()
    return await describe_configuration(provider_code)
