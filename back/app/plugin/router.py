"""Administration API for local declarative plugins."""

import asyncio
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from core.authorize import Privileges, authorize, public

from . import catalog, runtime, service
from .bundles import MAX_UPLOAD_BYTES, Bundle, BundleError, read_bundle
from .contracts import Digest, HostConfirmation, InventoryEntry, PluginCode, PluginDetail, Preview, Release, SampleConfirmation, Version

router = APIRouter(prefix="/plugins", tags=["plugins"])


async def _uploaded_bundle(file: UploadFile) -> tuple[Bundle, bytes]:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        return await asyncio.to_thread(read_bundle, content), content
    except BundleError as exc:
        status = 413 if exc.code == "archive_too_large" else 422
        raise HTTPException(status_code=status, detail=exc.code) from exc


@router.get("")
@authorize(privileges=[Privileges.PLUGIN_ACCESS, Privileges.PLUGIN_EDIT])
async def list_plugins() -> list[InventoryEntry]:
    return await service.list_plugins()


@router.post("/preview")
@authorize(privileges=Privileges.PLUGIN_EDIT)
async def inspect_plugin(file: UploadFile = File(...)) -> Preview:
    bundle, _ = await _uploaded_bundle(file)
    return service.inspect_bundle(bundle)


@router.post("/install")
@authorize(privileges=Privileges.PLUGIN_EDIT)
async def install_plugin(
    file: UploadFile = File(...),
    digest: Digest = Form(...),
    host_identity: Digest = Form(...),
    force: bool = Form(False),
) -> Release:
    bundle, content = await _uploaded_bundle(file)
    try:
        return await service.install(bundle, content, digest, force, host_identity)
    except service.PluginError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc


@router.get("/catalog")
@authorize(privileges=Privileges.PLUGIN_EDIT)
async def list_plugin_catalogue() -> list[Preview]:
    try:
        bundles = await asyncio.to_thread(catalog.list_catalogue)
        return [service.inspect_bundle(bundle) for bundle in bundles]
    except (OSError, ValueError) as exc:
        raise HTTPException(503, detail="catalog_unavailable") from exc


@router.get("/catalog/{digest}")
@authorize(privileges=Privileges.PLUGIN_EDIT)
async def download_plugin_catalogue_archive(digest: Digest) -> Response:
    try:
        content = await asyncio.to_thread(catalog.catalogue_archive, digest)
    except (OSError, ValueError) as exc:
        raise HTTPException(503, detail="catalog_unavailable") from exc
    if content is None:
        raise HTTPException(404, detail="not_found")
    return Response(content, media_type="application/zip", headers={"Cache-Control": "no-store"})


@router.get("/{code}")
@authorize(privileges=[Privileges.PLUGIN_ACCESS, Privileges.PLUGIN_EDIT])
async def get_plugin(code: PluginCode) -> PluginDetail:
    try:
        return await service.plugin_detail(code)
    except service.PluginError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc


@router.get("/assets/{digest}/{code}.mjs", include_in_schema=False)
@public("Public browser code for an active, explicitly trusted executable plugin. No document or user data.")
async def executable_asset(digest: Digest, code: PluginCode) -> Response:
    content = runtime.frontend_asset(digest, code)
    if content is None:
        raise HTTPException(404)
    return Response(content, media_type="text/javascript", headers={"Cache-Control": "no-store"})


@router.get("/{code}/templates/{template_code}")
@authorize(privileges=[Privileges.PLUGIN_ACCESS, Privileges.PLUGIN_EDIT])
async def download_plugin_data_template(code: PluginCode, template_code: PluginCode) -> Response:
    try:
        content = await service.active_template(code, template_code)
    except service.PluginError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    except BundleError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    return Response(content, media_type="application/json", headers={
        "Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="{template_code}.json"',
    })


@router.post("/{code}/{version}/{operation}")
@authorize(privileges=Privileges.PLUGIN_EDIT)
async def change_plugin_state(
    code: PluginCode, version: Version, operation: Literal["activate", "deactivate", "remove"],
    confirmation: HostConfirmation | SampleConfirmation,
) -> InventoryEntry:
    try:
        expected_host = confirmation.host_identity if isinstance(confirmation, HostConfirmation) else None
        return await service.change_state(code, version, operation, expected_host)
    except service.PluginError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
