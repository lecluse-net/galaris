"""Shared avatar decoding and optimistic publication preconditions."""

import hashlib
import io
import json
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from core.database import get_db
from .models import Agent, Title

MAX_AVATAR_BYTES = 15 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000
MAX_STORED_AVATAR_SIDE = 512


def validate_avatar(content: bytes) -> None:
    if not content or len(content) > MAX_AVATAR_BYTES:
        raise ValueError("Avatar must contain between 1 byte and 15 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {"JPEG", "PNG", "GIF", "WEBP"}:
                    raise ValueError("Unsupported avatar image format")
                if image.width * image.height > MAX_AVATAR_PIXELS or max(image.size) > 8192:
                    raise ValueError("Avatar dimensions exceed the supported limit")
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid avatar image") from exc


def normalize_avatar(content: bytes) -> bytes:
    """Store a compact, correctly oriented JPEG without enlarging or cropping it."""
    validate_avatar(content)
    with Image.open(io.BytesIO(content)) as source:
        with ImageOps.exif_transpose(source) as image:
            # JPEG has no alpha channel. Composite transparent and palette images on white.
            with image.convert("RGBA") as rgba:
                rgba.thumbnail((MAX_STORED_AVATAR_SIDE, MAX_STORED_AVATAR_SIDE), Image.Resampling.LANCZOS)
                with Image.new("RGB", rgba.size, "white") as rgb:
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                    output = io.BytesIO()
                    rgb.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue()


async def portrait_snapshot(agent: Agent, *, lock_title: bool = False) -> dict[str, object]:
    query = select(Title).where(Title.id == agent.title_id).execution_options(populate_existing=True)
    title = await get_db().scalar(query.with_for_update() if lock_title else query)
    description = {"first_name": agent.first_name, "last_name": agent.last_name,
                   "gender": title.gender if title else None, "personality": agent.personality,
                   "job_title": agent.job_title, "job_description": agent.job_description,
                   "manager": agent.user_id}
    return {"target_id": agent.id, "avatar_revision": agent.avatar_revision,
            "fingerprint": hashlib.sha256(json.dumps(description, sort_keys=True).encode()).hexdigest(),
            "description": description}


async def apply_generated_avatar(target_id: int, content: bytes, snapshot: dict[str, object]) -> dict[str, object]:
    """Caller owns the commit, together with the durable Process receipt."""
    content = normalize_avatar(content)
    agent = await get_db().scalar(select(Agent).where(Agent.id == target_id).with_for_update()
                                  .execution_options(populate_existing=True))
    if agent is None:
        raise LookupError("Agent not found")
    current = await portrait_snapshot(agent, lock_title=True)
    if (current["fingerprint"] != snapshot["fingerprint"]
            or current["avatar_revision"] != snapshot["avatar_revision"]):
        raise ValueError("Avatar conflict: the target profile or avatar changed after admission")
    agent.avatar = content
    agent.avatar_revision += 1
    await get_db().flush()
    return {"agent_id": target_id, "resource_uri": f"galaris://agent/{target_id}",
            "status": "success", "registered": True, "avatar_revision": agent.avatar_revision}
