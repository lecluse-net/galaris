"""Authorization contract for the administrative failure journal."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from core.authorize import Privileges

from app.incident.router import (
    cleanup_incidents,
    patch_pattern,
    read_incident,
    read_incidents,
    read_recent_incidents,
    read_patterns,
)
from app.incident.schemas import FailureIncidentSummaryRead


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    credentials = {
        "email": "incident-admin@example.com",
        "password": "incident-admin-password",
    }
    registration = await client.post("/api/auth/register", json=credentials)
    assert registration.status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_router_declares_distinct_read_and_edit_privileges() -> None:
    for endpoint in (
        read_incidents,
        read_patterns,
        read_recent_incidents,
        read_incident,
    ):
        assert endpoint._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
            Privileges.INCIDENT_ACCESS,
            Privileges.INCIDENT_EDIT,
        ]
    assert patch_pattern._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        Privileges.INCIDENT_EDIT
    ]
    assert cleanup_incidents._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        Privileges.INCIDENT_PURGE
    ]


@pytest.mark.asyncio
async def test_journal_rejects_unauthenticated_requests(client: AsyncClient) -> None:
    assert (await client.get("/api/incidents")).status_code == 401
    assert (await client.get("/api/incidents/recent")).status_code == 401
    assert (await client.get("/api/incidents/patterns")).status_code == 401
    assert (await client.delete("/api/incidents/cleanup")).status_code == 401


def test_recent_incident_contract_exposes_no_error_detail() -> None:
    assert set(FailureIncidentSummaryRead.model_fields) == {
        "id",
        "kind",
        "recovered_at",
        "occurred_at",
    }


@pytest.mark.asyncio
async def test_admin_can_read_and_reaches_edit_endpoint(client: AsyncClient) -> None:
    headers = await _admin_headers(client)

    listing = await client.get("/api/incidents", headers=headers)
    recent = await client.get("/api/incidents/recent", headers=headers)
    edit = await client.patch(
        f"/api/incidents/patterns/{uuid4()}",
        headers=headers,
        json={"status": "triaged"},
    )
    cleanup = await client.delete("/api/incidents/cleanup", headers=headers)

    assert listing.status_code == 200
    assert listing.json()["page_size"] == 50
    assert recent.status_code == 200
    assert recent.json()["page_size"] == 5
    assert edit.status_code == 404
    assert cleanup.status_code == 204
