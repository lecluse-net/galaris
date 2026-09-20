"""Asynchronous client for the public n8n API and webhooks."""

from __future__ import annotations

from typing import Any, Optional, cast

import httpx
from core.i18n import t

from .errors import N8NError, from_http_status, network_error


class N8NClient:
    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        *,
        timeout: float = 15.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        absolute: bool = False,
    ) -> dict[str, Any]:
        target = url if absolute else f"{self.api_base_url}/{url.lstrip('/')}"
        request_headers = dict(headers or {})
        if not absolute:
            if not self.api_key:
                raise N8NError(
                    "not_configured", t("process.n8n.api_key_missing")
                )
            request_headers["X-N8N-API-KEY"] = self.api_key
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method, target, params=params, json=json, headers=request_headers
                )
        except httpx.TimeoutException as exc:
            raise N8NError("engine_timeout", str(exc), retryable=True) from exc
        except httpx.HTTPError as exc:
            raise network_error(exc) from exc
        if response.status_code >= 400:
            detail = response.text[:2000]
            raise from_http_status(
                response.status_code,
                f"n8n HTTP {response.status_code}: {detail or response.reason_phrase}",
            )
        if not response.content:
            return {}
        try:
            value: Any = response.json()
        except ValueError:
            return {"text": response.text[:2000]}
        if isinstance(value, dict):
            return {str(key): child for key, child in cast(dict[Any, Any], value).items()}
        return {"data": value}

    async def _list_all(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        query = dict(params or {})
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            if cursor:
                query["cursor"] = cursor
            payload = await self._request("GET", path, params=query)
            data = payload.get("data")
            if not isinstance(data, list):
                raise N8NError("invalid_response", t("process.n8n.invalid_api_response"))
            rows.extend(
                {str(key): value for key, value in cast(dict[Any, Any], item).items()}
                for item in cast(list[Any], data)
                if isinstance(item, dict)
            )
            cursor_value = payload.get("nextCursor")
            cursor = str(cursor_value) if cursor_value else None
            if not cursor:
                break
        return rows

    async def list_workflows(self, *, active: bool | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if active is not None:
            params["active"] = str(active).lower()
        return await self._list_all("workflows", params=params)

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return await self._request("GET", f"workflows/{workflow_id}")

    async def update_workflow(
        self, workflow_id: str, definition: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request("PUT", f"workflows/{workflow_id}", json=definition)

    async def create_credential(
        self, *, name: str, credential_type: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "credentials",
            json={"name": name, "type": credential_type, "data": data},
        )

    async def list_credentials(self) -> list[dict[str, Any]]:
        return await self._list_all("credentials")

    async def list_executions(
        self, workflow_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": max(1, min(limit, 250))}
        if workflow_id:
            params["workflowId"] = workflow_id
        return await self._list_all("executions", params=params)

    async def get_execution(self, execution_id: str) -> dict[str, Any]:
        return await self._request("GET", f"executions/{execution_id}", params={"includeData": "true"})

    async def stop_execution(self, execution_id: str) -> dict[str, Any]:
        try:
            return await self._request("POST", f"executions/{execution_id}/stop")
        except N8NError as exc:
            if exc.code in {"not_found", "invalid_request"}:
                raise N8NError(
                    "cancel_unsupported",
                    t("process.n8n.cancel_api_unavailable"),
                ) from exc
            raise

    async def call_webhook(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        if not url.lower().startswith(("http://", "https://")):
            raise N8NError(
                "invalid_webhook_url", t("process.n8n.invalid_webhook_url")
            )
        return await self._request(
            "POST", url, json=payload, headers=headers, absolute=True
        )
