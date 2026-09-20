"""Authenticated client for Meta's official WhatsApp Cloud Graph API."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import httpx
from core.util import as_dict
from app.messenger.interface import DeliveryOutcomeUnknown


class WhatsAppAPIError(RuntimeError):
    """Token-free, bounded representation of a Graph API failure."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        safe_message = re.sub(
            r"(?<!\w)\+?\d(?:[\s().-]*\d){5,}(?!\w)",
            "[redacted-number]",
            message,
        )
        safe_message = re.sub(
            r"(?i)\b(?:bearer|token|secret)\s*[:=]?\s*\S+",
            "[redacted-secret]",
            safe_message,
        )
        super().__init__(f"WhatsApp API {status_code}/{code}: {safe_message[:500]}")


class WhatsAppMediaTooLarge(ValueError):
    """Raised before an inbound media response can exceed the configured memory bound."""


class WhatsAppClient:
    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        graph_url: str,
        graph_version: str,
        timeout: float,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.phone_number_id = phone_number_id
        self._token = access_token
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=f"{graph_url.rstrip('/')}/{graph_version.strip('/')}",
            timeout=httpx.Timeout(timeout),
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    @staticmethod
    def _error(response: httpx.Response) -> WhatsAppAPIError:
        code = "unknown"
        message = response.reason_phrase or "request failed"
        try:
            payload = as_dict(response.json())
            error = as_dict(payload.get("error"))
            code = str(error.get("code") or error.get("error_subcode") or code)
            message = str(error.get("message") or message)
        except ValueError:
            pass
        return WhatsAppAPIError(response.status_code, code, message)

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        replay_safe = method.upper() in {"GET", "HEAD"}
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        delay = 1.0
        for attempt in range(1, 4):
            try:
                response = await self._http.request(method, url, headers=headers, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if not replay_safe:
                    raise DeliveryOutcomeUnknown(
                        "WhatsApp mutation outcome is uncertain; no automatic resend"
                    ) from exc
                if attempt == 3:
                    raise
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8.0)
                continue
            if response.status_code < 400:
                return response
            if not replay_safe:
                if response.status_code >= 500:
                    raise DeliveryOutcomeUnknown(
                        "WhatsApp mutation returned a server error; delivery is uncertain"
                    )
                raise self._error(response)
            if response.status_code != 429 and response.status_code < 500:
                raise self._error(response)
            if attempt == 3:
                raise self._error(response)
            raw_retry = response.headers.get("Retry-After", "")
            try:
                retry_after = float(raw_retry)
            except ValueError:
                retry_after = delay
            await asyncio.sleep(max(0.1, min(retry_after, 60.0)))
            delay = min(delay * 2, 8.0)
        raise RuntimeError("WhatsApp request unexpectedly exhausted")

    async def validate(self) -> dict[str, Any]:
        response = await self._request(
            "GET", f"/{self.phone_number_id}", params={"fields": "id,verified_name"}
        )
        data: dict[str, Any] = response.json()
        return data

    async def send_text(
        self,
        to: str,
        text: str,
        *,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        response = await self._request(
            "POST", f"/{self.phone_number_id}/messages", json=payload
        )
        data: dict[str, Any] = response.json()
        return data

    async def send_template(
        self,
        to: str,
        *,
        name: str,
        language: str,
        text_parameter: str = "",
    ) -> dict[str, Any]:
        template: dict[str, Any] = {
            "name": name,
            "language": {"code": language},
        }
        if text_parameter:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": text_parameter}],
                }
            ]
        response = await self._request(
            "POST",
            f"/{self.phone_number_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "template",
                "template": template,
            },
        )
        data: dict[str, Any] = response.json()
        return data

    async def upload_media(self, content: bytes, name: str, mime: str) -> str:
        response = await self._request(
            "POST",
            f"/{self.phone_number_id}/media",
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (name, content, mime)},
        )
        media_id = str(response.json().get("id") or "")
        if not media_id:
            raise WhatsAppAPIError(response.status_code, "missing_media_id", "No media ID")
        return media_id

    async def send_media(
        self,
        to: str,
        *,
        kind: str,
        media_id: str,
        name: str = "",
        caption: str | None = None,
        reply_to: str | None = None,
        voice: bool = False,
    ) -> dict[str, Any]:
        media: dict[str, Any] = {"id": media_id}
        if caption and kind in {"image", "video", "document"}:
            media["caption"] = caption
        if kind == "document" and name:
            media["filename"] = name
        if kind == "audio" and voice:
            media["voice"] = True
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": kind,
            kind: media,
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        response = await self._request(
            "POST", f"/{self.phone_number_id}/messages", json=payload
        )
        data: dict[str, Any] = response.json()
        return data

    async def _download_bytes(self, url: str, *, max_bytes: int) -> bytes:
        delay = 1.0
        for attempt in range(1, 4):
            try:
                async with self._http.stream(
                    "GET", url, headers=self._headers()
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        error = self._error(response)
                        retryable = response.status_code == 429 or response.status_code >= 500
                        if not retryable or attempt == 3:
                            raise error
                        raw_retry = response.headers.get("Retry-After", "")
                        try:
                            retry_after = float(raw_retry)
                        except ValueError:
                            retry_after = delay
                    else:
                        raw_length = response.headers.get("Content-Length", "")
                        try:
                            content_length = int(raw_length) if raw_length else None
                        except ValueError as exc:
                            raise WhatsAppAPIError(
                                response.status_code,
                                "invalid_content_length",
                                "Invalid media Content-Length",
                            ) from exc
                        if content_length is not None and content_length > max_bytes:
                            raise WhatsAppMediaTooLarge(
                                "WhatsApp media exceeds the configured size limit"
                            )
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(content) + len(chunk) > max_bytes:
                                raise WhatsAppMediaTooLarge(
                                    "WhatsApp media exceeds the configured size limit"
                                )
                            content.extend(chunk)
                        return bytes(content)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 3:
                    raise
                retry_after = delay
            await asyncio.sleep(max(0.1, min(retry_after, 60.0)))
            delay = min(delay * 2, 8.0)
        raise RuntimeError("WhatsApp media download unexpectedly exhausted")

    async def download_media(
        self,
        media_id: str,
        *,
        max_bytes: int,
    ) -> tuple[bytes, str]:
        metadata = await self._request("GET", f"/{media_id}")
        payload = metadata.json()
        url = str(payload.get("url") or "")
        if not url:
            raise WhatsAppAPIError(metadata.status_code, "missing_media_url", "No media URL")
        content = await self._download_bytes(url, max_bytes=max_bytes)
        return content, str(payload.get("mime_type") or "application/octet-stream")

    async def download_media_to_file(self, media_id: str, dest: Path, *, max_bytes: int) -> int:
        from core.util import copy_download

        async with asyncio.timeout(120):
            metadata = await self._request("GET", f"/{media_id}")
            url = str(metadata.json().get("url") or "")
            if not url:
                raise WhatsAppAPIError(metadata.status_code, "missing_media_url", "No media URL")
            async with self._http.stream("GET", url, headers=self._headers()) as response:
                response.raise_for_status()
                return await copy_download(response.aiter_bytes(min(64 * 1024, max_bytes + 1)), dest, max_bytes=max_bytes)
