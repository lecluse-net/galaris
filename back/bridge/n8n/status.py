"""Normalize n8n-specific execution statuses."""

from __future__ import annotations


def normalize_status(value: object) -> str:
    status = str(value or "").strip().lower().replace("_", "-")
    if status in {"new", "queued"}:
        return "queued"
    if status in {"running", "active"}:
        return "running"
    if status in {"waiting", "wait", "waiting-for-webhook"}:
        return "waiting"
    if status in {"success", "succeeded", "completed"}:
        return "success"
    if status in {"error", "failed", "crashed"}:
        return "error"
    if status in {"canceled", "cancelled", "stopped"}:
        return "cancelled"
    return "unknown"
