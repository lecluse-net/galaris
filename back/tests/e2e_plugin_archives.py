"""Frozen synthetic plugin versions for the isolated full-stack browser suite."""

from hashlib import sha256
from io import BytesIO
import json
import re
from typing import Literal
from zipfile import ZipFile, ZipInfo

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Response

from core import settings

router = APIRouter(prefix="/api/__test/plugin-archives")
_KEY = Ed25519PrivateKey.from_private_bytes(sha256(b"public synthetic plugin e2e fixture signing key").digest())
_CODE = "fixture.revision-editor"
_LABEL = {"fr": "Éditeur de qualification", "en": "Qualification editor"}
_BACKEND_V1 = '''from app.document import DocumentFormatDefinition

def plugin_format(_context):
    return DocumentFormatDefinition(
        "fixture.revision-editor", "application/octet-stream", "", "description", lambda _: None,
        lambda _: "", provider="fixture.revision-editor", storage_kind="file",
        initial_binary=b"Original qualification content", validate_binary=lambda _: None,
        surfaces=frozenset({"editor"}), import_extensions=(".bin",),
    )
'''
_FRONTEND_V1 = '''export function createFormat({ vue }) {
  return {
    editor: vue.defineComponent({ props: ['source'], setup(props) {
      const text = vue.ref('')
      vue.watch(() => props.source, async (source, previous, cleanup) => {
        const controller = new AbortController()
        cleanup(() => controller.abort())
        if (source) {
          const blob = await source.load(controller.signal)
          if (!controller.signal.aborted) text.value = await blob.text()
        }
      }, { immediate: true })
      return () => vue.h('p', text.value)
    }}),
    snapshot: async () => '<p>Qualification snapshot</p>',
  }
}
'''


def configure() -> None:
    settings.PLUGIN_TRUSTED_PUBLISHERS = {**settings.PLUGIN_TRUSTED_PUBLISHERS,
        "fixture": _KEY.public_key().public_bytes_raw().hex()}
    settings.PLUGIN_EXECUTABLE_PUBLISHERS = [*settings.PLUGIN_EXECUTABLE_PUBLISHERS, "fixture"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", settings.APP_VERSION):
        type(settings).APP_VERSION = "0.3.2"


def _fixture(version: Literal["1.0.0", "2.0.0"]) -> bytes:
    backend = (_BACKEND_V1 if version == "1.0.0" else "def invalid syntax").encode()
    frontend = _FRONTEND_V1.encode()
    manifest = json.dumps({"format_version": 2, "code": _CODE, "version": version, "label": _LABEL,
        "description": _LABEL, "minimum_galaris_version": "0.1.0", "maximum_galaris_version_exclusive": "999.0.0",
        "contributions": [{"family": "document_format", "code": _CODE, "label": _LABEL, "version": 1,
            "contract_version": 1, "sha256": sha256(backend).hexdigest(), "frontend_sha256": sha256(frontend).hexdigest()}]},
        sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    target = BytesIO()
    with ZipFile(target, "w") as archive:
        for name, content in (("manifest.json", manifest), ("manifest.sig", _KEY.sign(manifest)),
            (f"backend/{_CODE}.py", backend), (f"frontend/{_CODE}.mjs", frontend)):
            archive.writestr(ZipInfo(name), content)
    return target.getvalue()


@router.get("/{version}")
async def fixture(version: Literal["1.0.0", "2.0.0"]) -> Response:
    return Response(_fixture(version), media_type="application/zip")
