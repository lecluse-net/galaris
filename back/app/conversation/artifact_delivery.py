"""Project Task artifacts onto ordinary conversation attachments."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote

from app.agent.contracts import WorkingResource, WorkingSet
from app.file_share import (
    ResourceContext,
    ResourceUriError,
    parse_resource_uri,
    resource_info,
)


AUTO_DELIVERY_TOOL = "conversation_task_notification"
MAX_PRESENTED_ARTIFACTS = 10
_LOCAL_LINK_PREFIXES = ("sandbox:", "file:", "/mnt/data/")
_CANONICAL_URI_PATTERN = re.compile(
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>()\[\]]+"
)
_FILE_PATH_PATTERN = re.compile(
    r"(?<![\w.-])(?:[\w.-]+/)*[\w.-]+\.[A-Za-z][A-Za-z0-9]{0,11}(?![\w.-])"
)


@dataclass(frozen=True, slots=True)
class PresentedArtifact:
    source_uri: str
    name: str


def _artifact_name(resource: WorkingResource) -> str:
    label = PurePosixPath(resource.label.replace("\\", "/")).name
    if label:
        return label
    locator = resource.reference.partition("://")[2]
    return PurePosixPath(unquote(locator).rstrip("/")).name or "file"


def _eligible_resources(working_set: WorkingSet) -> list[WorkingResource]:
    resources: list[WorkingResource] = []
    for resource in working_set.active():
        if resource.resource_type != "artifact":
            continue
        if (
            resource.role != "final_artifact"
            and resource.metadata.get("produced") is not True
        ):
            continue
        try:
            reference = parse_resource_uri(resource.reference)
        except ResourceUriError:
            continue
        if reference.is_collection or reference.scheme in {
            "galaris",
            "memory",
            "document",
        }:
            continue
        resources.append(resource)
    return sorted(resources, key=lambda item: item.role != "final_artifact")


def _explicitly_referenced(text: str, resource: WorkingResource) -> bool:
    reference = resource.reference
    decoded = unquote(reference)
    return reference in text or (decoded != reference and decoded in text)


def _mentions_name(text: str, name: str) -> bool:
    return re.search(
        rf"(?<![\w.-]){re.escape(name)}(?![\w.-])",
        text,
        flags=re.IGNORECASE,
    ) is not None


def presented_artifacts(
    working_set: WorkingSet,
    result_text: str,
) -> tuple[PresentedArtifact, ...]:
    """Resolve only server-verified produced files that the result presents."""

    eligible = _eligible_resources(working_set)
    selected: list[WorkingResource] = []
    selected_names: set[str] = set()
    for resource in eligible:
        name = _artifact_name(resource)
        if (
            _explicitly_referenced(result_text, resource)
            and name.casefold() not in selected_names
        ):
            selected.append(resource)
            selected_names.add(name.casefold())

    by_name: dict[str, list[WorkingResource]] = {}
    for resource in eligible:
        by_name.setdefault(_artifact_name(resource).casefold(), []).append(resource)
    for normalized_name, resources in by_name.items():
        if normalized_name in selected_names:
            continue
        name = _artifact_name(resources[0])
        if not _mentions_name(result_text, name):
            continue
        finals = [item for item in resources if item.role == "final_artifact"]
        if len(resources) == 1:
            selected.append(resources[0])
        elif len(finals) == 1:
            selected.append(finals[0])
        else:
            continue
        selected_names.add(normalized_name)

    return tuple(
        PresentedArtifact(source_uri=item.reference, name=_artifact_name(item))
        for item in selected[:MAX_PRESENTED_ARTIFACTS]
    )


def _referenced_file_values(text: str) -> tuple[str, ...]:
    values: list[str] = []
    values.extend(
        match.group(0).rstrip(".,;:!?")
        for match in _CANONICAL_URI_PATTERN.finditer(text)
    )
    values.extend(
        match.group(1).strip()
        for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text)
    )
    values.extend(
        match.group(1).strip() for match in re.finditer(r"`([^`]+)`", text)
    )
    values.extend(
        match.group(0).strip() for match in _FILE_PATH_PATTERN.finditer(text)
    )
    return tuple(dict.fromkeys(value for value in values if value))


def _local_path(value: str) -> str:
    normalized = unquote(value).replace("\\", "/").strip()
    for prefix in (
        "sandbox:/mnt/data/",
        "file:///workspace/",
        "/mnt/data/",
    ):
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix).lstrip("/")
    return normalized.lstrip("./")


async def resolve_presented_artifacts(
    ctx: ResourceContext,
    working_set: WorkingSet,
    result_text: str,
) -> tuple[PresentedArtifact, ...]:
    """Add existing explicitly presented resources missed by the effect ledger."""

    selected = list(presented_artifacts(working_set, result_text))
    selected_uris = {item.source_uri for item in selected}
    selected_names = {item.name.casefold() for item in selected}
    for value in _referenced_file_values(result_text):
        if len(selected) >= MAX_PRESENTED_ARTIFACTS:
            break
        probes: list[str] = []
        runtime_local = value.startswith(_LOCAL_LINK_PREFIXES)
        try:
            parsed = None if runtime_local else parse_resource_uri(value)
        except ResourceUriError:
            parsed = None
        if parsed is not None and "://" in value:
            if parsed.scheme not in {"galaris", "memory", "document"}:
                probes.append(str(parsed))
        else:
            path = _local_path(value)
            if (
                path
                and not path.endswith("/")
                and ctx.console_resource is not None
            ):
                try:
                    probes.append(str(parse_resource_uri(f"console://{path}")))
                except ResourceUriError:
                    pass
        for uri in probes:
            if uri in selected_uris:
                break
            try:
                descriptor = await resource_info(ctx, uri)
            except (OSError, RuntimeError, ValueError):
                continue
            if descriptor.is_collection:
                continue
            name = descriptor.name or PurePosixPath(
                parse_resource_uri(uri).decoded_locator
            ).name
            if not name or name.casefold() in selected_names:
                break
            selected.append(PresentedArtifact(source_uri=descriptor.uri, name=name))
            selected_uris.add(descriptor.uri)
            selected_names.add(name.casefold())
            break
    return tuple(selected)


def clean_artifact_references(
    text: str,
    artifacts: tuple[PresentedArtifact, ...],
) -> str:
    """Replace technical and runtime-local links after their attachment succeeded."""

    cleaned = text
    for artifact in artifacts:
        targets = {artifact.source_uri, unquote(artifact.source_uri)}
        for target in sorted(targets, key=len, reverse=True):
            cleaned = re.sub(
                rf"\[([^\]]*)\]\({re.escape(target)}\)",
                lambda match, name=artifact.name: match.group(1).strip() or name,
                cleaned,
            )
            cleaned = cleaned.replace(f"<{target}>", artifact.name)
            cleaned = cleaned.replace(target, artifact.name)

        def replace_local_link(match: re.Match[str], name: str = artifact.name) -> str:
            label, target = match.group(1).strip(), match.group(2).strip()
            normalized = unquote(target).replace("\\", "/")
            if not normalized.endswith(f"/{name}"):
                return match.group(0)
            if not normalized.startswith(_LOCAL_LINK_PREFIXES):
                return match.group(0)
            return label or name

        cleaned = re.sub(r"\[([^\]]*)\]\(([^)]+)\)", replace_local_link, cleaned)
        cleaned = re.sub(
            rf"(?:sandbox:|file:)(?:/{{1,3}})?[^\s)>]*/{re.escape(artifact.name)}",
            artifact.name,
            cleaned,
        )
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def delivery_receipt_role(source_uri: str, connection_id: int, room_id: object) -> str:
    identity = f"{source_uri}\0{connection_id}\0{room_id}".encode()
    digest = hashlib.sha256(identity).hexdigest()[:24]
    return f"delivery_receipt:auto:{digest}"


def was_automatically_delivered(
    working_set: WorkingSet,
    artifact: PresentedArtifact,
    connection_id: int,
    room_id: object,
) -> bool:
    role = delivery_receipt_role(artifact.source_uri, connection_id, room_id)
    return any(
        resource.role == role
        and resource.resource_type == "delivery_receipt"
        and resource.metadata.get("tool") == AUTO_DELIVERY_TOOL
        and resource.metadata.get("delivered") is True
        for resource in working_set.active()
    )


def was_delivered_to_room(
    working_set: WorkingSet,
    artifact: PresentedArtifact,
    connection_id: int,
    room_ids: tuple[str, ...],
) -> bool:
    """Accept automatic receipts and exact model-initiated room deliveries."""

    if any(
        was_automatically_delivered(working_set, artifact, connection_id, room_id)
        for room_id in room_ids
    ):
        return True
    targets = {item for item in room_ids if item}
    for resource in working_set.active():
        if resource.resource_type != "delivery_receipt":
            continue
        metadata = resource.metadata
        if metadata.get("delivered") is False:
            continue
        if metadata.get("connection_id") is not None and str(metadata["connection_id"]) != str(connection_id):
            continue
        if str(metadata.get("destination") or "") not in targets:
            continue
        sources = {
            str(metadata.get("filename") or ""),
            str(metadata.get("source") or ""),
            str(metadata.get("uri") or ""),
        }
        if artifact.source_uri in sources or artifact.source_uri == resource.reference:
            return True
    return False


__all__ = [
    "AUTO_DELIVERY_TOOL",
    "PresentedArtifact",
    "clean_artifact_references",
    "delivery_receipt_role",
    "presented_artifacts",
    "resolve_presented_artifacts",
    "was_automatically_delivered",
    "was_delivered_to_room",
]
