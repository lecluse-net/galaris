"""Unified HTTP client for a Hermes API server instance."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, AsyncIterator, Dict, Optional
from urllib.parse import quote

import httpx
from loguru import logger

from core.i18n import render_prompt, t
from core.util import as_dict, as_list, get_encryption_service

# Hermes runs tools, memory, and reasoning, so reads need a generous timeout.
HERMES_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)


class HermesRunNotFound(RuntimeError):
    """The Hermes server no longer knows a previously persisted run."""


class HermesApprovalNotPending(RuntimeError):
    """The Hermes run no longer has an approval that can be resolved."""


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"hermes.errors.{key}"), **values)


def _decrypt_token(value: str) -> str:
    enc = get_encryption_service()
    return enc.decrypt(value) if enc.is_encrypted(value) else value


@dataclass
class HermesTarget:
    """Hermes instance addressed by URL, API key, and model."""
    url: str
    api_key: str = field(repr=False)
    model: str

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        agent_code: str,
    ) -> "HermesTarget":
        url = str(config.get("url") or "").strip()
        api_key = str(config.get("api_key") or "").strip()
        model = str(config.get("model") or "").strip()
        if not url or not api_key or not model:
            raise ValueError(_error(
                "configuration_incomplete", agent_code=agent_code
            ))
        return cls(url=url, api_key=_decrypt_token(api_key), model=model)

# ─────────────────────────────────────────────────────────────────────────────
# Hermes API server: persistent sessions and structured SSE runs.
# ─────────────────────────────────────────────────────────────────────────────


def _root_url(target: HermesTarget) -> str:
    """Return the Hermes API root where /api endpoints live outside /v1."""
    url = target.url.rstrip("/")
    return url[: -len("/v1")] if url.endswith("/v1") else url


def _v1_url(target: HermesTarget) -> str:
    """Return an OpenAI-compatible root from a URL with or without /v1."""
    url = target.url.rstrip("/")
    return url if url.endswith("/v1") else f"{url}/v1"


def _auth_headers(target: HermesTarget) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {target.api_key}",
        "Content-Type": "application/json",
    }


def _run_headers(target: HermesTarget, session_key: Optional[str] = None) -> Dict[str, str]:
    headers = _auth_headers(target)
    if session_key:
        headers["X-Hermes-Session-Key"] = session_key
    return headers


async def ensure_session(
    target: HermesTarget,
    session_id: str,
    *,
    title: Optional[str] = None,
) -> None:
    """Create a Hermes session when absent; treat HTTP 409 as success."""
    endpoint = f"{_root_url(target)}/api/sessions"
    payload: Dict[str, Any] = {"id": session_id, "model": target.model}
    if title:
        payload["title"] = title
    try:
        async with httpx.AsyncClient(timeout=HERMES_TIMEOUT) as http:
            response = await http.post(endpoint, headers=_auth_headers(target), json=payload)
            if response.status_code == 409:
                logger.debug("Hermes ensure_session: session {} already exists", session_id)
                return
            response.raise_for_status()
            logger.debug("Hermes ensure_session: created session {}", session_id)
    except httpx.HTTPStatusError as e:
        logger.error("Hermes ensure_session: HTTP {} from {}: {}",
                     e.response.status_code, endpoint, e.response.text[:500])
        raise
    except httpx.TransportError as e:
        logger.error("Hermes ensure_session: transport error from {}: {}", endpoint, e)
        raise RuntimeError(_error("connect_failed", error=e)) from e


async def get_session(target: HermesTarget, session_id: str) -> Optional[Dict[str, Any]]:
    """Return Hermes session accounting data, or null when unavailable."""
    endpoint = f"{_root_url(target)}/api/sessions/{quote(session_id, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=HERMES_TIMEOUT) as http:
            response = await http.get(endpoint, headers=_auth_headers(target))
            if response.status_code != 200:
                return None
            data = response.json()
            session = data.get("session", data)
            return as_dict(session) if isinstance(session, dict) else None
    except (httpx.TransportError, ValueError) as e:
        logger.warning("Hermes get_session failed for {}: {}", endpoint, e)
        return None


def session_cost(session: Optional[Dict[str, Any]]) -> float:
    """Return cumulative session USD cost, preferring actual over estimated."""
    if not session:
        return 0.0
    try:
        actual = float(session.get("actual_cost_usd") or 0.0)
        estimated = float(session.get("estimated_cost_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return actual if actual > 0 else estimated


async def get_session_messages(target: HermesTarget, session_id: str) -> list[dict[str, Any]]:
    """Return persistent Hermes session history in API format."""
    endpoint = (
        f"{_root_url(target)}/api/sessions/{quote(session_id, safe='')}/messages"
    )
    try:
        async with httpx.AsyncClient(timeout=HERMES_TIMEOUT) as http:
            res = await http.get(endpoint, headers=_auth_headers(target))
            if res.status_code == 404:
                return []
            res.raise_for_status()
            data = res.json()
            messages = as_dict(data).get("data") if isinstance(data, dict) else None
            return as_list(messages) if isinstance(messages, list) else []
    except (httpx.TransportError, ValueError) as e:
        logger.warning("Hermes get_session_messages failed for {}: {}", endpoint, e)
        return []


async def start_run(
    target: HermesTarget,
    *,
    session_id: str,
    message: Any,
    system_message: Optional[str] = None,
    conversation_history: Optional[list[dict[str, Any]]] = None,
    session_key: Optional[str] = None,
) -> str:
    """Start a controllable Hermes run through /v1/runs."""
    endpoint = f"{_v1_url(target)}/runs"
    input_payload: Any
    if isinstance(message, str):
        input_payload = message
    else:
        input_payload = [{"role": "user", "content": message}]
    payload: Dict[str, Any] = {
        "input": input_payload,
        "session_id": session_id,
        "model": target.model,
    }
    if system_message:
        payload["instructions"] = system_message
    if conversation_history:
        payload["conversation_history"] = conversation_history

    async with httpx.AsyncClient(timeout=HERMES_TIMEOUT) as http:
        res = await http.post(
            endpoint,
            headers=_run_headers(target, session_key or session_id),
            json=payload,
        )
        res.raise_for_status()
        data = res.json()
        run_id = as_dict(data).get("run_id") if isinstance(data, dict) else None
        if not run_id:
            raise RuntimeError(_error("run_id_missing"))
        return str(run_id)


async def run_events(
    target: HermesTarget,
    run_id: str,
    *,
    language: str = "en",
) -> AsyncIterator[Dict[str, Any]]:
    """Stream structured Hermes run events over SSE."""
    endpoint = f"{_v1_url(target)}/runs/{run_id}/events"
    try:
        async with httpx.AsyncClient(timeout=HERMES_TIMEOUT) as http:
            async with http.stream("GET", endpoint, headers=_auth_headers(target)) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    error_msg = error_body.decode("utf-8", errors="replace")
                    yield {
                        "event": "error",
                        "data": {
                            "message": render_prompt(
                                t("hermes.errors.run_events_http", language),
                                status=response.status_code,
                                error=error_msg[:300],
                            )
                        },
                    }
                    return

                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        logger.warning("Hermes run_events ignored non-JSON SSE data: {}", line[:200])
                        continue
                    event_name = as_dict(data).get("event") if isinstance(data, dict) else None
                    yield {"event": event_name or "message", "data": data}
    except httpx.TransportError as e:
        logger.error("Hermes run_events transport error from {}: {}", endpoint, e)
        yield {
            "event": "error",
            "data": {
                "message": render_prompt(
                    t("hermes.errors.connect_failed", language),
                    error=e,
                )
            },
        }


async def get_run_status(target: HermesTarget, run_id: str) -> Dict[str, Any]:
    """Return the pollable status of an existing Hermes run."""

    endpoint = f"{_v1_url(target)}/runs/{run_id}"
    async with httpx.AsyncClient(timeout=HERMES_TIMEOUT) as http:
        response = await http.get(endpoint, headers=_auth_headers(target))
        if response.status_code == 404:
            raise HermesRunNotFound(run_id)
        response.raise_for_status()
        data = response.json()
        return as_dict(data) if isinstance(data, dict) else {}


async def stop_run(target: HermesTarget, run_id: str) -> Dict[str, Any]:
    """Request cooperative cancellation of an active Hermes run."""
    endpoint = f"{_v1_url(target)}/runs/{run_id}/stop"
    async with httpx.AsyncClient(timeout=HERMES_TIMEOUT) as http:
        response = await http.post(endpoint, headers=_auth_headers(target))
        if response.status_code == 404:
            raise HermesRunNotFound(run_id)
        response.raise_for_status()
        data = response.json()
        return as_dict(data) if isinstance(data, dict) else {}


async def submit_run_approval(target: HermesTarget, run_id: str, choice: str) -> Dict[str, Any]:
    """Submit a choice for a pending Hermes run approval."""
    endpoint = f"{_v1_url(target)}/runs/{run_id}/approval"
    async with httpx.AsyncClient(timeout=HERMES_TIMEOUT) as http:
        res = await http.post(
            endpoint,
            headers=_auth_headers(target),
            json={"choice": choice},
        )
        if res.status_code == 404:
            raise HermesRunNotFound(run_id)
        if res.status_code == 409:
            raise HermesApprovalNotPending(run_id)
        res.raise_for_status()
        data = res.json()
        return as_dict(data) if isinstance(data, dict) else {}
