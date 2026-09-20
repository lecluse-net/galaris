"""Opaque checkpoint negotiation at the driver composition boundary."""

from copy import deepcopy

from .contracts import (
    AgentDriverError, AgentRunCheckpoint, CheckpointAssessment, DriverCheckpointPolicy,
)
from .registry import resolve_checkpoint_factory, get_driver_spec
from .execution_errors import HarnessCheckpointError


def checkpoint_policy(code: str) -> DriverCheckpointPolicy | None:
    spec = get_driver_spec(code)
    if "checkpoints" not in spec.execution_capabilities or spec.checkpoint_policy_path is None:
        return None
    policy = resolve_checkpoint_factory(spec.checkpoint_policy_path)()
    if not isinstance(policy, DriverCheckpointPolicy):
        raise TypeError(f"Driver {code!r} has an invalid checkpoint policy.")
    return policy


def assess_checkpoint(checkpoint: AgentRunCheckpoint) -> CheckpointAssessment:
    try:
        policy = checkpoint_policy(checkpoint.driver_code)
    except AgentDriverError:
        return CheckpointAssessment(state="unsafe", reason="Checkpoint driver is unavailable.")
    if policy is None:
        return CheckpointAssessment(state="unsafe", reason="Driver has no checkpoint recovery contract.")
    return CheckpointAssessment.model_validate(policy.assess(deepcopy(checkpoint)).model_dump())


def rebase_checkpoint(checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint:
    policy = checkpoint_policy(checkpoint.driver_code)
    rebased = None if policy is None else policy.rebase(deepcopy(checkpoint))
    if rebased is None:
        raise HarnessCheckpointError("The driver cannot safely rebase this checkpoint after an objective amendment.")
    if rebased.driver_code != checkpoint.driver_code:
        raise HarnessCheckpointError("Rebasing cannot transfer a checkpoint to another driver.")
    return rebased
