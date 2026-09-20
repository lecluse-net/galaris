"""Qualify the real Matrix adapter with two dedicated accounts and an explicit test room."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from bridge.matrix.client import Matrix
from bridge.matrix.messenger import MatrixMessenger


async def qualify(sender: Matrix, observer: Matrix, room: str, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Evidence already exists; inspect it before explicitly starting another qualification")
    evidence: dict[str, Any] = {"qualified": False, "room": room, "started_at": datetime.now(timezone.utc).isoformat(),
                                "scope": "Matrix adapter text and file reception; no inbound task or other bridge qualification"}
    output.parent.mkdir(parents=True, exist_ok=True)

    def save() -> None:
        output.write_text(json.dumps(evidence, indent=2) + "\n")

    save()
    try:
        expected = (sender.user_id, observer.user_id)
        identities = (await sender.whoami(), await observer.whoami())
        if identities != expected or identities[0] == identities[1]:
            raise ValueError("Two distinct, explicitly identified test accounts are required")
        if await sender.room_is_encrypted(room):
            raise ValueError("The Galaris Matrix adapter requires an unencrypted test room")
        sending, receiving = MatrixMessenger(sender), MatrixMessenger(observer)
        await receiving.history(room, limit=1)  # Verify observer access before any send.
        marker = f"Galaris qualification {uuid4()}"
        content = (marker + "\nSynthetic file, no user data.\n").encode()
        evidence["content_sha256"] = hashlib.sha256(content).hexdigest()
        evidence["delivery_state"] = "text_submission_started"
        save()
        message = await sending.send_to_room(room, marker)
        evidence["message_event"] = message.id
        evidence["delivery_state"] = "file_submission_started"
        save()
        attachment = await sending.upload_file(room, content, name="galaris-qualification.txt")
        evidence["file_event"] = attachment.id
        evidence["delivery_state"] = "awaiting_observer"
        save()
        async with asyncio.timeout(45):
            while True:
                messages = {entry.id: entry for entry in await receiving.history(room, limit=50)}
                if message.id in messages and attachment.id in messages:
                    text = messages[message.id]
                    file = messages[attachment.id]
                    if text.sender is None or file.sender is None or text.text != marker or text.sender.id != sender.user_id or file.sender.id != sender.user_id:
                        raise ValueError("Observer received different content or sender")
                    if len(file.attachments) != 1 or await receiving.fetch_attachment(file.attachments[0]) != content:
                        raise ValueError("Observer did not receive the exact original file")
                    evidence["qualified"] = True
                    evidence["delivery_state"] = "observed"
                    evidence["observer"] = observer.user_id
                    return evidence
                await asyncio.sleep(0.5)
    except Exception as error:
        evidence["error_type"] = type(error).__name__
        raise
    finally:
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
        await sender.aclose()
        await observer.aclose()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homeserver", required=True)
    parser.add_argument("--sender", required=True)
    parser.add_argument("--observer", required=True)
    parser.add_argument("--send-to-room", required=True, help="Explicitly authorized, dedicated test room")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    address = urlparse(str(args.homeserver))
    if address.scheme != "https" or address.username or address.password:
        parser.error("Homeserver must use HTTPS without URL credentials")
    sender_token = os.environ.get("MATRIX_QUALIFICATION_SENDER_TOKEN")
    observer_token = os.environ.get("MATRIX_QUALIFICATION_OBSERVER_TOKEN")
    if not sender_token or not observer_token:
        parser.error("Dedicated MATRIX_QUALIFICATION_SENDER_TOKEN and MATRIX_QUALIFICATION_OBSERVER_TOKEN are required")
    result = await qualify(
        Matrix(args.homeserver, args.sender, sender_token, media_max_bytes=4096),
        Matrix(args.homeserver, args.observer, observer_token, media_max_bytes=4096),
        args.send_to_room, args.output,
    )
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
