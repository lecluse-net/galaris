"""Small retrying wrapper around the official asynchronous Telegram Bot SDK."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Awaitable, Callable, Sequence, TypeVar

from loguru import logger
import httpx
from core.util import copy_download
from telegram import Bot, InputFile, Message as TelegramMessage, ReplyParameters, Update, User
from telegram.error import NetworkError, RetryAfter, TimedOut
from app.messenger.interface import DeliveryOutcomeUnknown

T = TypeVar("T")


class TelegramClient:
    """Own one SDK bot and consistently apply bounded network/rate-limit retries."""

    def __init__(self, token: str, *, bot: Bot | None = None) -> None:
        self._bot = bot or Bot(token=token)
        self._initialized = False

    async def initialize(self) -> User:
        if not self._initialized:
            await self._bot.initialize()
            self._initialized = True
        return await self._retry("getMe", self._bot.get_me)

    async def aclose(self) -> None:
        if self._initialized:
            await self._bot.shutdown()
            self._initialized = False

    async def _retry(self, operation: str, call: Callable[[], Awaitable[T]]) -> T:
        replay_safe = operation in {"getMe", "getUpdates", "getFile", "downloadFile", "deleteWebhook"}
        delay = 1.0
        for attempt in range(1, 4):
            try:
                return await call()
            except RetryAfter as exc:
                raw = exc.retry_after
                retry_after = raw.total_seconds() if isinstance(raw, timedelta) else float(raw)
                if attempt == 3:
                    raise
                sleep_for = max(0.1, min(retry_after, 60.0))
                logger.warning(
                    "Telegram rate limit operation={} retry={} delay={}s",
                    operation,
                    attempt,
                    sleep_for,
                )
                await asyncio.sleep(sleep_for)
            except (TimedOut, NetworkError) as exc:
                if not replay_safe:
                    raise DeliveryOutcomeUnknown(
                        f"Telegram {operation} delivery is uncertain; no automatic resend"
                    ) from exc
                if attempt == 3:
                    raise
                logger.warning(
                    "Telegram transient error operation={} retry={} delay={}s",
                    operation,
                    attempt,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8.0)
        raise RuntimeError(f"Telegram operation unexpectedly exhausted: {operation}")

    async def delete_webhook(self) -> None:
        await self._retry(
            "deleteWebhook",
            lambda: self._bot.delete_webhook(drop_pending_updates=False),
        )

    async def get_updates(self, *, offset: int | None, timeout: int) -> Sequence[Update]:
        return await self._retry(
            "getUpdates",
            lambda: self._bot.get_updates(
                offset=offset,
                timeout=timeout,
                limit=100,
                allowed_updates=["message", "edited_message"],
                # The HTTP read must outlive Telegram's server-side long poll.
                read_timeout=float(timeout) + 10.0,
            ),
        )

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_to: int | None = None,
    ) -> TelegramMessage:
        return await self._retry(
            "sendMessage",
            lambda: self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_parameters=(
                    ReplyParameters(message_id=reply_to) if reply_to is not None else None
                ),
            ),
        )

    async def send_file(
        self,
        chat_id: str,
        content: bytes,
        name: str,
        mime: str,
        *,
        caption: str | None = None,
        reply_to: int | None = None,
    ) -> TelegramMessage:
        reply = ReplyParameters(message_id=reply_to) if reply_to is not None else None
        if mime.startswith("image/"):
            return await self._retry(
                "sendPhoto",
                lambda: self._bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(content, filename=name),
                    caption=caption,
                    reply_parameters=reply,
                ),
            )
        return await self._retry(
            "sendDocument",
            lambda: self._bot.send_document(
                chat_id=chat_id,
                document=InputFile(content, filename=name),
                caption=caption,
                reply_parameters=reply,
            ),
        )

    async def send_voice(
        self,
        chat_id: str,
        path: Path,
        *,
        caption: str | None = None,
        reply_to: int | None = None,
    ) -> TelegramMessage:
        content = await asyncio.to_thread(path.read_bytes)
        return await self._retry(
            "sendVoice",
            lambda: self._bot.send_voice(
                chat_id=chat_id,
                voice=InputFile(content, filename=path.name),
                caption=caption,
                reply_parameters=(
                    ReplyParameters(message_id=reply_to) if reply_to is not None else None
                ),
            ),
        )

    async def download(self, file_id: str) -> bytes:
        remote = await self._retry("getFile", lambda: self._bot.get_file(file_id))
        content = await self._retry("downloadFile", remote.download_as_bytearray)
        return bytes(content)

    async def download_to_file(self, file_id: str, dest: Path, *, max_bytes: int) -> int:
        remote = await self._retry("getFile", lambda: self._bot.get_file(file_id))
        if remote.file_size is not None and remote.file_size > max_bytes:
            raise ValueError("Telegram attachment exceeds the requested byte limit")
        if not remote.file_path or not remote.file_path.startswith(("http://", "https://")):
            raise ValueError("Telegram attachment has no HTTP download reference")
        async with asyncio.timeout(120):
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                async with client.stream("GET", remote.file_path) as response:
                    response.raise_for_status()
                    return await copy_download(response.aiter_bytes(min(64 * 1024, max_bytes + 1)), dest, max_bytes=max_bytes)
