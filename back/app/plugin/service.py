"""Transactional installation and selection of declarative plugin releases."""

import asyncio
from collections.abc import Callable
from hashlib import sha256
import re
from typing import Literal
from uuid import uuid4

from loguru import logger
from pydantic import TypeAdapter
from sqlalchemy import func, select

from app.services import ServiceCreate
from app.services.facade import ServicePreset, preset, read_catalog
from core import settings
from core.database import get_db
from core.update_diagnostics import record_update_failure
from core.user import get_current_user_id

from . import runtime
from .bundles import Bundle, publisher_key, read_bundle
from .contracts import (
    Compatibility, FileShareProtocolContribution, InventoryEntry, Manifest, Operation, PluginDetail, PluginEventRead, Preview,
    PresetContribution, Release, SampleRelease, TemplateContribution, version_parts,
)
from .models import DevelopmentSampleState, PluginEvent, PluginRelease

_PRESETS = TypeAdapter(list[ServiceCreate])
_HOST_VERSION = re.compile(r"(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}")
_SESSION_REVISION = uuid4().hex
_samples: dict[str, SampleRelease] = {}
_sample_presets: tuple[ServiceCreate, ...] = ()
_disabled_samples: frozenset[str] = frozenset()
_runtime_changes = asyncio.Lock()


def register_development_samples(samples: list[SampleRelease], presets: list[ServiceCreate]) -> None:
    """Bind the reference plugins shipped in the development checkout."""
    global _samples, _sample_presets
    _samples = {sample.manifest.code: sample for sample in samples}
    _sample_presets = tuple(presets)


def development_sample_is_active(code: str) -> bool:
    return settings.is_dev and code in _samples and code not in _disabled_samples


def _sample_release(sample: SampleRelease) -> SampleRelease:
    return sample.model_copy(update={"active": development_sample_is_active(sample.manifest.code)})


class PluginError(ValueError):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def host_identity() -> str:
    revision = settings.APP_BUILD_REVISION
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        revision = _SESSION_REVISION
    return sha256(f"{settings.APP_ENV}:{settings.APP_VERSION}:{revision}".encode()).hexdigest()


def _compatibility(manifest: Manifest, signer: str, presets: list[ServiceCreate]) -> Compatibility:
    key = publisher_key(manifest.publisher)
    if key is None or sha256(key).hexdigest() != signer:
        return "untrusted_publisher"
    if manifest.executable and manifest.publisher not in settings.PLUGIN_EXECUTABLE_PUBLISHERS:
        return "native_publisher_required"
    if not runtime.dependencies_available(manifest.python_requirements):
        return "missing_dependency"
    if any(runtime.runtime_endpoint(requirement) is None for requirement in manifest.runtime_requirements):
        return "runtime_unconfigured"
    declared_protocols = frozenset(f"{item.code}.file_share" for item in manifest.contributions
                                   if isinstance(item, FileShareProtocolContribution))
    if any(not preset(definition, declared_protocols=declared_protocols).compatible for definition in presets):
        return "unsupported_service"
    version = settings.APP_VERSION
    if not _HOST_VERSION.fullmatch(version) or not (
        version_parts(manifest.minimum_galaris_version)
        <= version_parts(version)
        < version_parts(manifest.maximum_galaris_version_exclusive)
    ):
        return "host_version"
    return "supported"


def inspect_bundle(bundle: Bundle) -> Preview:
    compatibility = _compatibility(bundle.manifest, bundle.signer, bundle.presets)
    return Preview(
        manifest=bundle.manifest,
        digest=bundle.digest,
        signer=bundle.signer,
        compatibility=compatibility,
        host_version=settings.APP_VERSION,
        host_identity=host_identity(),
        can_force=settings.is_dev and compatibility == "host_version",
    )


def _release(record: PluginRelease) -> Release:
    manifest = Manifest.model_validate_json(record.manifest)
    compatibility = _compatibility(manifest, record.signer, _PRESETS.validate_json(record.presets))
    forced = settings.is_dev and record.forced_host == host_identity()
    return Release(
        manifest=manifest,
        digest=record.digest,
        signer=record.signer,
        host_version=settings.APP_VERSION,
        host_identity=host_identity(),
        compatibility=compatibility,
        can_force=settings.is_dev and compatibility == "host_version",
        installed=record.installed,
        selected=record.active,
        active=record.active and (compatibility == "supported" or compatibility == "host_version" and forced)
        and (not manifest.executable or runtime.effective(record.digest)),
        forced=forced,
    )


async def _lock_plugins() -> None:
    await get_db().execute(select(func.pg_advisory_xact_lock(func.hashtextextended("plugin-releases", 0))))


async def _get_release(code: str, version: str) -> PluginRelease | None:
    return await get_db().scalar(select(PluginRelease).where(
        PluginRelease.code == code, PluginRelease.version == version,
    ))


async def _checked_archive(record: PluginRelease) -> Bundle:
    archive = await get_db().scalar(select(PluginRelease.archive).where(PluginRelease.id == record.id))
    if archive is None:
        raise PluginError("not_installed")
    bundle = await asyncio.to_thread(read_bundle, archive)
    if (bundle.digest != record.digest or bundle.signer != record.signer
            or bundle.manifest != Manifest.model_validate_json(record.manifest)):
        raise PluginError("invalid_bundle")
    return bundle


async def _record_failure(error: Exception, *, operation: str, stage: str,
                          code: str, version: str, digest: str = "") -> None:
    details = {
        "command": f"plugin:{operation}", "stage": stage, "plugin_code": code,
        "plugin_version": version,
    }
    if digest:
        details["archive_fingerprint"] = digest[:16]
    path = await asyncio.to_thread(record_update_failure, error, details=details)
    logger.error("Plugin operation failed code={} version={} digest={} operation={} stage={} error_type={} diagnostic={}",
                 code, version, digest, operation, stage, type(error).__name__, path or "unavailable")


async def _restore_sample_states() -> None:
    global _disabled_samples
    _disabled_samples = frozenset(await get_db().scalars(
        select(DevelopmentSampleState.code).where(DevelopmentSampleState.active.is_(False)),
    )) if settings.is_dev and _samples else frozenset()


async def restore_executable_plugins() -> None:
    """Restore enabled checkout samples and compatible signed releases before serving."""
    await _restore_sample_states()
    records = (await get_db().scalars(select(PluginRelease).where(PluginRelease.active).order_by(PluginRelease.code))).all()
    runtime.prepare_generation(())()
    for record in records:
        release = _release(record)
        if not release.manifest.executable or not (
            release.compatibility == "supported" or release.compatibility == "host_version" and release.forced
        ):
            continue
        stage = "verify_archive"
        try:
            bundle = await _checked_archive(record)
            stage = "probe_dependencies"
            await runtime.verify_runtimes(bundle.manifest.runtime_requirements)
            stage = "publish_registries"
            runtime.prepare_change(record.code, bundle)()
        except Exception as exc:
            await _record_failure(exc, operation="startup", stage=stage,
                                  code=record.code, version=record.version, digest=record.digest)


def _event(record: PluginRelease, operation: Operation, *, forced: bool = False) -> None:
    get_db().add(PluginEvent(
        release_id=record.id,
        user_id=get_current_user_id(),
        operation=operation,
        forced=forced,
        host_version=settings.APP_VERSION if forced else None,
        host_revision=settings.APP_BUILD_REVISION if forced else None,
        host_identity=host_identity() if forced else None,
    ))


async def install(bundle: Bundle, content: bytes, digest: str, force: bool, expected_host: str) -> Release:
    async with _runtime_changes:
        try:
            return await _install(bundle, content, digest, force, expected_host)
        except PluginError:
            raise
        except Exception as exc:
            await _record_failure(exc, operation="install", stage="store_release", code=bundle.manifest.code,
                                  version=bundle.manifest.version, digest=bundle.digest)
            raise


async def _install(bundle: Bundle, content: bytes, digest: str, force: bool, expected_host: str) -> Release:
    if digest != bundle.digest:
        raise PluginError("preview_changed")
    if force and not settings.is_dev:
        raise PluginError("force_forbidden", 403)
    report = inspect_bundle(bundle)
    if report.compatibility != "supported":
        if not (force and report.can_force and expected_host == report.host_identity):
            raise PluginError(report.compatibility)
    forced_host = report.host_identity if report.compatibility == "host_version" else None
    code, version = bundle.manifest.code, bundle.manifest.version
    if settings.is_dev and (sample := _samples.get(code)) is not None and sample.target == "documents":
        raise PluginError("development_sample")
    await _lock_plugins()
    db = get_db()
    other_signer = await db.scalar(select(PluginRelease.signer).where(
        PluginRelease.code == code, PluginRelease.signer != bundle.signer,
    ).limit(1))
    if other_signer is not None:
        raise PluginError("publisher_conflict")
    record = await _get_release(code, version)
    if record is not None and record.digest != bundle.digest:
        raise PluginError("version_conflict")
    if record is not None and record.installed and record.forced_host == forced_host:
        return _release(record)
    publish: Callable[[], None] | None = None
    if record is None:
        record = PluginRelease(
            code=code, version=version, digest=bundle.digest, signer=bundle.signer,
            manifest=bundle.manifest.model_dump_json(), presets=_PRESETS.dump_json(bundle.presets).decode(),
            active=False, installed=True, archive=content, forced_host=forced_host,
        )
        db.add(record)
        await db.flush()
    else:
        record.installed = True
        record.archive = content
        record.presets = _PRESETS.dump_json(bundle.presets).decode()
        if record.forced_host != forced_host:
            # Renewing an installation's host exception always requires fresh activation.
            if runtime.effective(record.digest):
                publish = runtime.prepare_change(code, None)
            record.active = False
        record.forced_host = forced_host
    _event(record, "installed", forced=forced_host is not None)
    await db.commit()
    if publish is not None:
        publish()
    return _release(record)


async def list_plugins() -> list[InventoryEntry]:
    records = (await get_db().scalars(select(PluginRelease))).all()
    releases = sorted(records, key=lambda item: (
        item.active, item.installed, version_parts(item.version)
    ), reverse=True)
    by_code: dict[str, PluginRelease] = {}
    for record in releases:
        by_code.setdefault(record.code, record)
    inventory: dict[str, InventoryEntry] = {
        code: _sample_release(sample) for code, sample in _samples.items()
    } if settings.is_dev else {}
    inventory.update((code, _release(record)) for code, record in by_code.items())
    return [inventory[code] for code in sorted(inventory)]


async def plugin_detail(code: str) -> PluginDetail:
    db = get_db()
    records = (await db.scalars(select(PluginRelease).where(PluginRelease.code == code))).all()
    if not records:
        if settings.is_dev and (sample := _samples.get(code)) is not None:
            return PluginDetail(code=code, releases=[_sample_release(sample)], events=[])
        raise PluginError("not_found", 404)
    events = (await db.execute(select(PluginEvent, PluginRelease.version).join(
        PluginRelease, PluginRelease.id == PluginEvent.release_id
    ).where(PluginRelease.code == code).order_by(PluginEvent.id.desc()).limit(50))).all()
    return PluginDetail(
        code=code,
        releases=[_release(record) for record in sorted(records, key=lambda item: version_parts(item.version), reverse=True)],
        events=[PluginEventRead(
            version=version, operation=event.operation, occurred_at=event.occurred_at, forced=event.forced,
        ) for event, version in events],
    )


async def active_presets() -> list[ServicePreset]:
    """Publish only effective declarations, with today's compatibility and trust."""
    records = (await get_db().scalars(select(PluginRelease).where(PluginRelease.active))).all()
    current = [preset(definition) for record in records if _release(record).active
               for definition in _PRESETS.validate_json(record.presets)]
    if settings.is_dev and _sample_presets:
        managed = set((await get_db().scalars(select(PluginRelease.code).where(
            PluginRelease.code.in_(_samples),
        ))).all())
        current.extend(preset(definition) for definition in _sample_presets
                       if definition.catalog and definition.catalog.plugin_code not in managed
                       and development_sample_is_active(definition.catalog.plugin_code or ""))
    return current


async def active_template(code: str, template_code: str) -> bytes:
    record = await get_db().scalar(select(PluginRelease).where(PluginRelease.code == code, PluginRelease.active))
    if record is not None and (release := _release(record)).active:
        for item in release.manifest.contributions:
            if isinstance(item, TemplateContribution) and item.code == template_code:
                bundle = await _checked_archive(record)
                return bundle.assets[item.path]
    raise PluginError("not_found", 404)


async def change_state(
    code: str, version: str, operation: Literal["activate", "deactivate", "remove"], expected_host: str | None,
) -> InventoryEntry:
    async with _runtime_changes:
        try:
            return await _change_state(code, version, operation, expected_host)
        except PluginError:
            raise
        except Exception as exc:
            await _record_failure(exc, operation=operation, stage="commit_selection", code=code, version=version)
            raise


async def _check_preset_conflicts(code: str, contributions: set[str]) -> None:
    if not contributions:
        return
    base = await asyncio.to_thread(read_catalog)
    occupied = {entry.definition.code for entry in base.entries}
    occupied.update(entry.definition.code for entry in await active_presets()
                    if entry.definition.catalog and entry.definition.catalog.plugin_code != code)
    if occupied.intersection(contributions):
        raise PluginError("preset_conflict")


async def _change_sample(sample: SampleRelease, operation: Literal["activate", "deactivate", "remove"]) -> SampleRelease:
    global _disabled_samples
    if operation == "remove":
        raise PluginError("development_sample")
    code = sample.manifest.code
    active = operation == "activate"
    db = get_db()
    saved = await db.scalar(select(DevelopmentSampleState).where(DevelopmentSampleState.code == code))
    if active != (saved is None or saved.active):
        if active:
            await _check_preset_conflicts(code, {item.code for item in sample.manifest.contributions
                                                  if item.family == "service_preset"})
        if saved is None:
            db.add(DevelopmentSampleState(code=code, active=active))
        else:
            saved.active = active
        await db.commit()
    _disabled_samples = _disabled_samples - {code} if active else _disabled_samples | {code}
    return _sample_release(sample)


async def _change_state(
    code: str, version: str, operation: Literal["activate", "deactivate", "remove"], expected_host: str | None,
) -> InventoryEntry:
    await _lock_plugins()
    db = get_db()
    record = await _get_release(code, version)
    sample = _samples.get(code) if settings.is_dev else None
    if expected_host is None:
        if sample is None or sample.manifest.version != version:
            raise PluginError("not_found", 404)
        if record is not None or await db.scalar(select(PluginRelease.id).where(PluginRelease.code == code).limit(1)) is not None:
            raise PluginError("preview_changed")
        return await _change_sample(sample, operation)
    if record is None:
        if sample is not None:
            raise PluginError("development_sample")
        raise PluginError("not_found", 404)
    summary = _release(record)
    publish: Callable[[], None] | None = None

    if operation == "activate":
        if not record.installed:
            raise PluginError("not_installed")
        if summary.compatibility != "supported" and not (
            summary.compatibility == "host_version" and summary.forced and expected_host == summary.host_identity
        ):
            raise PluginError(summary.compatibility)
        if summary.active:
            return summary
        await _check_preset_conflicts(code, {item.code for item in summary.manifest.contributions
                                             if isinstance(item, PresetContribution)})
        previous = await db.scalar(select(PluginRelease).where(PluginRelease.code == code, PluginRelease.active))
        if summary.manifest.executable or previous is not None and runtime.effective(previous.digest):
            stage = "verify_archive"
            try:
                replacement = await _checked_archive(record) if summary.manifest.executable else None
                if replacement is not None:
                    stage = "probe_dependencies"
                    await runtime.verify_runtimes(replacement.manifest.runtime_requirements)
                stage = "prepare_registries"
                publish = runtime.prepare_change(code, replacement)
            except Exception as exc:
                await _record_failure(exc, operation="activate", stage=stage,
                                      code=record.code, version=record.version, digest=record.digest)
                try:
                    _event(record, "activation_error")
                    await db.commit()
                except Exception as receipt_error:
                    await _record_failure(receipt_error, operation="activate", stage="store_failure_event",
                                          code=summary.manifest.code, version=summary.manifest.version, digest=summary.digest)
                raise PluginError("activation_error") from None
        if previous is not None and previous.id != record.id:
            previous.active = False
            _event(previous, "deactivated")
            await db.flush()
        record.active = True
        _event(record, "activated", forced=summary.compatibility == "host_version")
    elif operation == "deactivate":
        if not record.active:
            return summary
        record.active = False
        if runtime.effective(record.digest):
            publish = runtime.prepare_change(code, None)
        _event(record, "deactivated")
    else:
        if record.active:
            raise PluginError("deactivate_first")
        if not record.installed:
            return summary
        record.installed = False
        record.archive = None
        record.presets = "[]"
        record.forced_host = None
        _event(record, "removed")
    await db.commit()
    if publish is not None:
        publish()
    return _release(record)
