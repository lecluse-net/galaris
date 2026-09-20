"""Project centrally assigned skill trees into the Hermes runtime data tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from app.agent import Agent
from app.skill import build_skill_projection, skill_service, storage
from core.database import get_db_session

if TYPE_CHECKING:
    from .manager import HermesManager


MANAGED_ROOT = "data/skills/galaris"
LEGACY_MANAGED_ROOT = "data/skills/galaris-managed"
MANIFEST_PATH = f"{MANAGED_ROOT}/.galaris-manifest.json"
MANIFEST_VERSION = 2


def collect_managed_files(codes: list[str]) -> dict[str, dict[str, Any]]:
    """Return complete remote paths and hashes for valid assigned skills."""
    desired: dict[str, dict[str, Any]] = {}
    for code in sorted(set(codes)):
        inspection = storage.inspect(code)
        if not inspection.valid:
            logger.warning(
                "Hermes skill projection skipped invalid skill: code={} error={}",
                code,
                inspection.validation_error,
            )
            continue
        remote_root = f"{MANAGED_ROOT}/{code}"
        for relative, path in storage.iter_skill_files(code):
            managed_path = f"{remote_root}/{relative}"
            desired[managed_path] = {
                "sha256": storage.file_hash(path),
                "size": path.stat().st_size,
                "source": path,
            }
    return desired


async def _assigned_codes(agent_id: int) -> list[str]:
    async with get_db_session():
        return await skill_service.get_assigned_codes(agent_id)


async def sync_managed_skills(agent: Agent, manager: "HermesManager") -> dict[str, int]:
    """Rebuild the Galaris-managed namespace from the assigned skill packages."""
    codes = await _assigned_codes(agent.id)
    snapshot = await build_skill_projection(agent.id, skill_codes=codes)
    desired: dict[str, dict[str, Any]] = {
        f"{MANAGED_ROOT}/{item.skill_code}/{item.relative_path}": {
            "sha256": item.sha256,
            "size": item.size,
            "source": item.source,
        }
        for item in snapshot.files
    }

    # This namespace is exclusively owned by Galaris. Purging it first removes
    # empty directories and untracked leftovers as well as manifest-known files.
    purged = 0
    for remote_root in (MANAGED_ROOT, LEGACY_MANAGED_ROOT):
        if await manager.delete_agent_tree(agent.code, remote_root):
            purged += 1

    uploaded = 0
    for remote_path, metadata in desired.items():
        source = cast(Path, metadata["source"])
        await manager.upload_agent_file_from(
            agent.code,
            remote_path,
            source,
        )
        uploaded += 1

    manifest = {
        "version": MANIFEST_VERSION,
        "skills": codes,
        "files": {
            remote_path: {
                "sha256": metadata["sha256"],
                "size": metadata["size"],
            }
            for remote_path, metadata in desired.items()
        },
    }
    await manager.write_agent_file(
        agent.code,
        MANIFEST_PATH,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    logger.info(
        "Hermes managed skills synchronized: agent={} skills={} uploaded={} purged_roots={}",
        agent.code,
        len(codes),
        uploaded,
        purged,
    )
    return {"skills": len(codes), "uploaded": uploaded, "unchanged": 0, "deleted": purged}
