"""Resolve the shared Nextcloud connection used by Talk and file sharing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.i18n import render_prompt, t


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)


@dataclass(frozen=True)
class NextcloudConnectionConfig:
    """Resolved non-secret metadata and credentials for one agent account."""

    connection_id: int
    agent_id: int
    tool_id: int
    base_url: str
    login: str
    password: str
    self_id: str


async def resolve_nextcloud_connection(connection_id: int) -> NextcloudConnectionConfig:
    """Resolve Talk independently from a Tool's optional file-sharing service."""
    from app.messenger import resolve_messenger_configuration

    resolved = await resolve_messenger_configuration(
        connection_id,
        expected_service="nextcloud_talk",
    )
    params = resolved.params
    base_url = resolved.settings.get("base_url", "").strip().rstrip("/")
    login = str(params.get("login") or "")
    password = str(params.get("password") or "")
    self_id = login

    if not base_url or not login or not password:
        raise ValueError(_error("talk_config_required"))

    return NextcloudConnectionConfig(
        connection_id=resolved.connection_id,
        agent_id=resolved.agent_id,
        tool_id=resolved.tool_id,
        base_url=base_url,
        login=login,
        password=password,
        self_id=self_id,
    )


__all__ = ["NextcloudConnectionConfig", "resolve_nextcloud_connection"]
