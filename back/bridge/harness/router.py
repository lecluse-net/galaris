"""Manager preferences, host setup exports and bounded connection diagnostics."""

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Response, Request

from core.authorize import Privileges, authorize, independent_auth
from core.params import runtime_settings
from .distribution import Release, ReleaseManifest, build_release

from .diagnostics import ManagerDiagnostics, diagnose
from .configuration import (
    ManagerConfiguration, ManagerConfigurationUpdate, ManagerHostSetup,
    configuration, export_environment, save_configuration,
)

router = APIRouter(prefix="/harness-manager", tags=["harness-manager"])


@router.get("/diagnostics", response_model=ManagerDiagnostics)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def manager_diagnostics() -> ManagerDiagnostics:
    return await diagnose()


@router.get("/configuration", response_model=ManagerConfiguration)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def read_configuration() -> ManagerConfiguration:
    return configuration()


@router.put("/configuration", response_model=ManagerConfiguration)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def update_configuration(data: ManagerConfigurationUpdate) -> ManagerConfiguration:
    return await save_configuration(data)


@router.post("/generate-secret")
@authorize(privileges=Privileges.PARAMS_EDIT)
async def generate_secret(response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return {"secret": Fernet.generate_key().decode("ascii")}


@router.post("/environment", response_class=Response)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def manager_environment(data: ManagerHostSetup) -> Response:
    try:
        content = export_environment(data)
    except ValueError:
        raise HTTPException(409, "Save a manager secret before exporting") from None
    return Response(content, media_type="text/plain", headers={"Cache-Control": "no-store"})


def _release(environment: str | None = None) -> Release:
    try:
        return build_release(environment)
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, "Manager distribution unavailable") from None


def _archive_response(release: Release, *, configured: bool = False) -> Response:
    suffix = "-configured" if configured else ""
    return Response(release.content, media_type="application/zip", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="harness-manager-{release.manifest.version}{suffix}.zip"',
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/release", response_model=ReleaseManifest)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
def release_manifest() -> ReleaseManifest:
    return _release().manifest


@router.get("/release.zip", response_class=Response)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
def release_archive() -> Response:
    return _archive_response(_release())


@router.post("/installation.zip", response_class=Response)
@authorize(privileges=Privileges.PARAMS_EDIT)
def installation_archive(data: ManagerHostSetup) -> Response:
    try:
        environment = export_environment(data)
    except ValueError:
        raise HTTPException(409, "Save a manager secret before exporting") from None
    return _archive_response(_release(environment), configured=True)


def _update_cipher(request: Request) -> Fernet:
    try:
        cipher = Fernet(runtime_settings.HARNESS_MANAGER_SECRET.encode())
        value = cipher.decrypt(request.headers.get("X-Harness-Token", "").encode(), ttl=60)
        if value != b"galaris-harness-update":
            raise ValueError("Invalid update capability")
        return cipher
    except (ValueError, InvalidToken):
        raise HTTPException(401, "Invalid manager update credential") from None


@router.get("/updates/manifest")
@independent_auth("Fernet manager update capability, authenticated with the configured shared secret and a 60-second TTL")
def update_manifest(request: Request) -> Response:
    cipher = _update_cipher(request)
    manifest = _release().manifest.model_dump_json().encode()
    return Response(cipher.encrypt(manifest), media_type="text/plain", headers={"Cache-Control": "no-store"})


@router.get("/updates/archive/{digest}.zip", response_class=Response)
@independent_auth("Fernet manager update capability, authenticated with the configured shared secret and a 60-second TTL")
def update_archive(request: Request, digest: str) -> Response:
    _update_cipher(request)
    release = _release()
    if digest != release.manifest.sha256:
        raise HTTPException(409, "The manager release changed; request a new manifest")
    return _archive_response(release)
