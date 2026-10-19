"""Scope rules use admitted demands, never profile, memory or planner prose."""
from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from uuid import UUID

from .scope_contracts import ExecutionScopeV1, EffectDescriptorV1, ScopeGrant, ScopePreflightV1, ScopeRequirement

SCOPE_KEY = "execution_scope"
PREFLIGHT_KEY = "scope_preflights"
_URI = re.compile(r"[a-z][a-z0-9+.-]*://[^\s<>\"']{1,1900}")


class ScopePlanError(ValueError):
    """A syntactically valid plan violates the admitted scope."""
    def __init__(self, message: str, *, needs_target: bool = False) -> None:
        super().__init__(message)
        self.needs_target = needs_target


def parse_scope(data: Mapping[str, object]) -> ExecutionScopeV1 | None:
    raw = data.get(SCOPE_KEY)
    return None if raw is None else ExecutionScopeV1.model_validate(raw)


def admitted_scope(task_id: UUID, demand: str, *, delivery_target: str | None = None,
                   source_reference: str | None = None,
                   resolved_write_targets: Sequence[str] = ()) -> ExecutionScopeV1:
    reference = source_reference or f"galaris://task/{task_id}"
    requirement = ScopeRequirement(key="demand", instruction=demand or "Complete the admitted task.", source_reference=reference)
    targets = set(_URI.findall(html.unescape(demand)))
    grants = [ScopeGrant(target=target, requirement_key="demand", source_reference=reference) for target in sorted(targets)]
    # Trusted root admission resolves implicit targets against its frozen source
    # and context. Resolution authorizes updates only, never deletion or transport.
    grants.extend(ScopeGrant(target=target, capability="file.write", requirement_key="demand",
                             source_reference=reference)
                  for target in sorted(set(resolved_write_targets) - targets))
    if delivery_target:
        grants.append(ScopeGrant(target=delivery_target, capability="messenger.send", requirement_key="demand", source_reference=reference))
    return ExecutionScopeV1(source_task_id=task_id, delivery_owner_task_id=task_id, requirements=(requirement,), grants=tuple(grants))


def amend_scope(scope: ExecutionScopeV1, instruction: str, source_reference: str) -> ExecutionScopeV1:
    key = f"amendment-{scope.revision + 1}"
    requirement = ScopeRequirement(key=key, instruction=instruction, source_reference=source_reference)
    grants = tuple(ScopeGrant(target=target, requirement_key=key, source_reference=source_reference)
                   for target in sorted(set(_URI.findall(html.unescape(instruction)))))
    return scope.model_copy(update={"revision": scope.revision + 1,
        "requirements": (*scope.requirements, requirement), "grants": (*scope.grants, *grants)})


def preflight(scope: ExecutionScopeV1 | None, descriptor: EffectDescriptorV1 | None,
              tool_name: str, arguments: Mapping[str, object], *, produced_targets: frozenset[str] = frozenset()) -> ScopePreflightV1:
    revision = scope.revision if scope else None
    if descriptor is None or scope is None:
        return ScopePreflightV1(tool_name=tool_name, scope_revision=revision, decision="allow_and_record",
            reason="Legacy scope or effect is unknown; existing domain authorization remains mandatory.")
    targets: list[str] = []
    for argument in descriptor.target_arguments:
        value = arguments.get(argument)
        if value is not None and value != "":
            if not isinstance(value, str) or len(value) > 2_000:
                return ScopePreflightV1(tool_name=tool_name, scope_revision=revision, decision="deny", reason="Invalid effect target.")
            targets.append(f"{descriptor.target_prefix}{value}")
    permitted = {grant.target for grant in scope.grants if grant.capability in {"*", descriptor.capability}}
    if (descriptor.domain_assigned_selection and descriptor.target_prefix and targets
            and not any(target.startswith(descriptor.target_prefix) for target in permitted)):
        return ScopePreflightV1(tool_name=tool_name, scope_revision=revision, decision="allow_and_record",
            reason="Owner-assigned catalog selection; live assignment and native authorization remain mandatory.",
            targets=tuple(targets))
    # Reading/discovery does not confer publication rights. New ordinary artifacts
    # remain autonomous; disclosure to a remote collection requires an exact grant.
    ordinary = descriptor.kind == "read" or (
        descriptor.kind == "create" and bool(targets)
        and all(target.partition("://")[0] in descriptor.ordinary_creation_schemes for target in targets)
    )
    if descriptor.kind == "mutate":
        permitted.update(produced_targets)
    allowed = ordinary or (bool(targets) and all(target in permitted for target in targets))
    return ScopePreflightV1(tool_name=tool_name, scope_revision=revision,
        decision="allow" if allowed else "clarify",
        reason="Effect is supported by admitted scope or ordinary production." if allowed else "Effect requires a sourced target amendment.",
        targets=tuple(targets))


def validate_plan_scope(scope: ExecutionScopeV1, steps: Sequence[object], *, required_keys: frozenset[str] | None = None) -> None:
    known = {requirement.key for requirement in scope.requirements}
    targets = {grant.target for grant in scope.grants}

    def visit(nodes: Sequence[object], allowed: set[str]) -> set[str]:
        covered: set[str] = set()
        for step in nodes:
            references: set[str] = set(getattr(step, "requirement_ids", ()))
            if references - allowed:
                raise ScopePlanError("Plan refers to unknown or out-of-group scope requirements.")
            if set(getattr(step, "target_refs", ())) - targets:
                raise ScopePlanError("Plan introduces an unsourced target.", needs_target=True)
            children = getattr(step, "steps", ())
            if children:
                leaves = visit(children, references or allowed)
                if references - leaves:
                    raise ScopePlanError("Plan group claims a requirement its leaves do not serve.")
                covered.update(leaves)
            else:
                if not references:
                    raise ScopePlanError("Plan leaf omits its sourced requirements.")
                covered.update(references)
        return covered

    covered = visit(steps, known)
    if (known if required_keys is None else required_keys) - covered:
        raise ScopePlanError("Plan omits an admitted scope requirement.")
