"""Correlate native delivery receipts with the artifact they acknowledge."""

from __future__ import annotations

import re
from html import unescape

from .contracts import WorkingResource


def references_exact_resource(text: str, reference: str) -> bool:
    """Match an already canonical URI as a whole reference in prose or HTML."""
    return re.search(
        rf"(?<![\w+./:@%-]){re.escape(reference)}(?=$|[\s<>'\"`)\],;]|[.!?](?=$|\s|<))",
        unescape(text),
    ) is not None


def receipt_source(receipt: WorkingResource) -> str:
    """Return the exact source URI recorded by the native delivery tool."""
    for key in ("filename", "source"):
        value = receipt.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def receipt_matches_artifact(artifact: WorkingResource, receipt: WorkingResource) -> bool:
    """Require a common producer, source and destination, without interpreting prose."""
    if (
        artifact.state != "active"
        or receipt.state != "active"
        or artifact.resource_type != "artifact"
        or artifact.metadata.get("delivered") is not True
        or not receipt.is_delivery_receipt
        or artifact.producer_task_id is None
        or artifact.producer_task_id != receipt.producer_task_id
    ):
        return False

    source = str(artifact.metadata.get("source") or "").strip()
    recorded_source = receipt_source(receipt)
    if source and source != recorded_source:
        return False

    destination_uri = str(receipt.metadata.get("uri") or "").strip()
    destination = str(receipt.metadata.get("destination") or "").strip()
    artifact_destination = str(
        artifact.metadata.get("delivery_destination")
        or artifact.metadata.get("destination") or ""
    ).strip()
    if artifact_destination and artifact_destination != destination:
        return False
    artifact_tool = artifact.metadata.get("file_share_tool")
    if artifact_tool is not None and artifact_tool != receipt.metadata.get("tool_code"):
        return False
    if not destination_uri and "://" in destination:
        destination_uri = destination
    if destination_uri:
        return artifact.reference == destination_uri

    if artifact_destination != destination:
        return False
    # Uploads and legacy Messenger responses may not return a destination URI.
    # Audio receipts use the same exact reference as their synthetic artifact.
    return bool(source) or artifact.reference in {recorded_source, receipt.reference}
