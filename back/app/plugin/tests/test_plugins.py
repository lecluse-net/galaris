"""Signed plugin receipts, compatibility and Service ownership through the API."""

import json
from hashlib import sha256
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from core import settings
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core import update_diagnostics
from core.user import UserModel, encrypt_password

from app.plugin.bundles import BundleError, read_bundle
from app.plugin.models import PluginEvent
from app.memory.tests.conftest import memory_storage as memory_storage


@pytest.fixture(autouse=True)
def diagnostic_directory(monkeypatch, tmp_path):
    root = tmp_path / "update-diagnostics"
    monkeypatch.setattr(update_diagnostics, "DIAGNOSTIC_ROOT", root)
    return root


@pytest.fixture
def bundle_factory(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", {
        "example": key.public_key().public_bytes_raw().hex(),
    })
    monkeypatch.setattr(type(settings), "APP_VERSION", "0.2.0")
    monkeypatch.setattr(type(settings), "APP_BUILD_REVISION", "a" * 40)

    def create(version="1.0.0", *, tampered=False, extra_file=None, code="synthetic-preset"):
        names = {"fr": "Service de test", "en": "Synthetic preset"}
        preset = json.dumps({
            "code": code, "label": names["en"], "catalog": {"version": version},
            "capabilities": ["rest.api"], "rest_config": {"base_url": "https://service.example.test"},
        }).encode()
        manifest = json.dumps({
            "format_version": 1, "code": "example.studio", "version": version,
            "label": {"en": "Synthetic studio", "fr": "Studio de test"},
            "description": {"en": "A synthetic bundle", "fr": "Une archive de test"},
            "minimum_galaris_version": "0.1.0", "maximum_galaris_version_exclusive": "0.3.0",
            "contributions": [{
                "family": "service_preset", "code": code, "label": names,
                "contract_version": 1, "sha256": sha256(preset).hexdigest(),
            }],
        }).encode()
        destination = BytesIO()
        with ZipFile(destination, "w") as archive:
            archive.writestr("manifest.json", manifest)
            archive.writestr("manifest.sig", key.sign(manifest))
            archive.writestr(f"services/{code}.yaml", preset + b" " if tampered else preset)
            if extra_file:
                archive.writestr(extra_file, "synthetic")
        return destination.getvalue()

    return create


async def _login(client, *privileges):
    suffix = uuid4().hex
    email = f"plugins-{suffix}@example.com"
    password = "synthetic-plugin-test-password"
    async with get_db_session() as db:
        granted = (await db.scalars(select(Privilege).where(Privilege.code.in_(privileges)))).all()
        role = Role(code=f"plugin-{suffix}", privileges=list(granted))
        user = UserModel(email=email, hashed_password=encrypt_password(password), is_active=True)
        db.add_all([role, user])
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
    client.cookies.clear()
    response = await client.post("/api/auth/login-json", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(archive):
    return {"file": ("synthetic.zip", archive, "application/zip")}


async def _preview(client, headers, archive):
    report = await client.post("/api/plugins/preview", headers=headers, files=_upload(archive))
    assert report.status_code == 200, report.text
    return report.json()


async def _install(client, headers, archive, report, force=False):
    return await client.post("/api/plugins/install", headers=headers, files=_upload(archive), data={
        "digest": report["digest"], "host_identity": report["host_identity"], "force": str(force),
    })


async def _change(client, headers, report, action):
    manifest = report["manifest"]
    return await client.post(f"/api/plugins/{manifest['code']}/{manifest['version']}/{action}", headers=headers,
                             json={"host_identity": report["host_identity"]})


async def _preset(client, headers):
    result = await client.get("/api/services/catalog", headers=headers)
    assert result.status_code == 200, result.text
    return next((item["definition"] for item in result.json()["entries"]
                 if item["definition"]["code"] == "synthetic-preset"), None)


@pytest.mark.asyncio
async def test_development_samples_appear_without_import_and_publish_their_presets(client, monkeypatch):
    from app.document import formats
    from app.plugin import service
    from plugins.sample.drawing import CODE, register as register_drawing
    from plugins.sample.inventory import ROOT, register
    from plugins.sample.package import build

    monkeypatch.setattr(service, "_samples", {})
    monkeypatch.setattr(service, "_sample_presets", ())
    monkeypatch.setattr(service, "_disabled_samples", frozenset())
    monkeypatch.setattr(formats, "registry", formats.DocumentFormatRegistry())
    monkeypatch.setattr(formats, "_native_registered", False)
    monkeypatch.setattr(formats, "_format_availability", {})
    register()
    register_drawing(available=lambda: service.development_sample_is_active(CODE))
    admin = await _login(client, "PLUGIN_EDIT", "SERVICE_EDIT", "DOCUMENT_ACCESS")
    reader = await _login(client, "PLUGIN_ACCESS")
    sample_codes = {"sample.drawing", "sample.rest", "sample.mcp"}
    assert (await client.get("/api/plugins", headers=admin)).json() == []
    assert (await client.get("/api/plugins/sample.drawing", headers=admin)).status_code == 404
    drawing_path = "/api/plugins/sample.drawing/1.0.0"
    sample_confirmation = {"source": "development_sample"}
    assert (await client.post(f"{drawing_path}/deactivate", headers=admin, json=sample_confirmation)).status_code == 404
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    result = await client.get("/api/plugins", headers=admin)
    assert result.status_code == 200, result.text
    entries = {item["manifest"]["code"]: item for item in result.json()}
    assert set(entries) == sample_codes
    assert all(item["source"] == "development_sample" and item["active"] for item in entries.values())
    detail = await client.get("/api/plugins/sample.drawing", headers=admin)
    assert detail.json()["releases"][0]["manifest"]["contributions"][0]["family"] == "document_format"
    assert (await client.post("/api/plugins/sample.drawing/1.0.0/remove", headers=admin,
                              json={"host_identity": "a" * 64})).status_code == 409
    assert (await client.post(f"{drawing_path}/deactivate", headers=reader, json=sample_confirmation)).status_code == 403
    assert (await client.post(f"{drawing_path}/deactivate", headers=admin, json=sample_confirmation)).json()["active"] is False
    assert CODE not in formats.document_format_codes()
    assert (await client.get("/api/plugins/sample.drawing", headers=admin)).json()["releases"][0]["active"] is False
    monkeypatch.setattr(service, "_disabled_samples", frozenset())
    async with get_db_session():
        await service._restore_sample_states()
    assert CODE not in formats.document_format_codes()
    assert (await client.post(f"{drawing_path}/activate", headers=admin, json=sample_confirmation)).json()["active"] is True
    assert CODE in formats.document_format_codes()
    catalogue = await client.get("/api/services/catalog", headers=admin)
    assert catalogue.status_code == 200, catalogue.text
    for name, protocol in (("rest", "rest.api"), ("mcp", "http.mcp")):
        row = next(item for item in catalogue.json()["entries"] if item["definition"]["code"] == f"sample-{name}")
        assert row["compatible"] and row["definition"]["capabilities"] == [protocol]
        assert row["definition"]["connection_schema"]["params"]["url"]["default"] == entries[f"sample.{name}"]["endpoint"]
        saved = await client.post("/api/services", headers=admin, json=row["definition"])
        assert saved.status_code == 201, saved.text
    rest_path = "/api/plugins/sample.rest/1.0.0"
    assert (await client.post(f"{rest_path}/deactivate", headers=admin, json=sample_confirmation)).json()["active"] is False
    catalogue = await client.get("/api/services/catalog", headers=admin)
    assert "sample-rest" not in {row["definition"]["code"] for row in catalogue.json()["entries"]}
    assert (await client.post(f"{rest_path}/activate", headers=admin, json=sample_confirmation)).json()["active"] is True
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(type(settings), "APP_VERSION", "0.2.0")
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", {"sample": key.public_key().public_bytes_raw().hex()})
    archive = build(ROOT / "rest", key)
    report = await _preview(client, admin, archive)
    assert (await _install(client, admin, archive, report)).status_code == 200
    assert (await client.post(f"{rest_path}/activate", headers=admin, json=sample_confirmation)).status_code == 409
    assert (await _change(client, admin, report, "activate")).status_code == 200
    assert (await _change(client, admin, report, "deactivate")).status_code == 200
    assert (await _change(client, admin, report, "remove")).status_code == 200
    catalogue = await client.get("/api/services/catalog", headers=admin)
    assert "sample-rest" not in {row["definition"]["code"] for row in catalogue.json()["entries"]}


@pytest.mark.parametrize(("options", "error"), [
    ({"tampered": True}, "invalid_signature"),
    ({"extra_file": "../outside"}, "invalid_bundle"),
    ({"extra_file": "entrypoint.py"}, "invalid_bundle"),
])
def test_bundle_rejects_unverified_or_undeclared_members(bundle_factory, options, error):
    with pytest.raises(BundleError, match=error):
        read_bundle(bundle_factory(**options))


def test_catalogue_publication_checks_provenance_and_preserves_release_history(bundle_factory, monkeypatch, tmp_path):
    from cryptography.exceptions import InvalidSignature

    from app.plugin.publication import stage_catalogue
    from app.plugin.remote_catalog import verify_signed_index
    from plugins.sample.inventory import ROOT
    from plugins.sample.package import build

    candidates = tmp_path / "candidates"
    candidates.mkdir()
    package = candidates / "sample.zip"
    proof = candidates / "sample.qualification.json"
    signature = candidates / "sample.qualification.sig"
    catalogue_key = Ed25519PrivateKey.generate()
    qualification_key = Ed25519PrivateKey.generate()
    reviewer = qualification_key.public_key()
    release = bundle_factory()
    digest = sha256(release).hexdigest()
    evidence = {
        "format_version": 1, "digest": digest, "source_repository": "https://source.example.test/studio",
        "source_commit": "a" * 40, "report_digest": "b" * 64,
        "checks": ["bundle", "compatibility", "permissions", "localization", "lifecycle"],
    }

    def attest():
        body = json.dumps(evidence).encode()
        proof.write_bytes(body)
        signature.write_bytes(qualification_key.sign(body))

    package.write_bytes(release)
    attest()
    head = tmp_path / "first"
    signature.write_bytes(b"x" * 64)
    with pytest.raises(InvalidSignature):
        stage_catalogue(candidates, head, catalogue_key, reviewer)
    assert not head.exists()
    attest()
    package.write_bytes(bundle_factory("1.1.0"))
    with pytest.raises(ValueError, match="archive digest"):
        stage_catalogue(candidates, head, catalogue_key, reviewer)
    package.write_bytes(release)
    first = stage_catalogue(candidates, head, catalogue_key, reviewer)
    signed = (head / "index.sig").read_bytes() + (head / "index.json").read_bytes()
    assert verify_signed_index(signed, catalogue_key.public_key().public_bytes_raw()) == first
    assert (head / "archives" / f"{digest}.zip").read_bytes() == release
    assert (head / "qualification" / f"{digest}.json").read_bytes() == proof.read_bytes()

    package.unlink()
    second = tmp_path / "second"
    index = stage_catalogue(candidates, second, catalogue_key, reviewer, previous=head, revoke=(digest,))
    assert index.sequence == first.sequence + 1
    assert index.revoked == [digest] and index.releases == first.releases
    assert not list((second / "archives").iterdir())
    assert (head / "archives" / f"{digest}.zip").read_bytes() == release
    package.write_bytes(release)
    with pytest.raises(ValueError, match="non-revoked"):
        stage_catalogue(candidates, tmp_path / "third", catalogue_key, reviewer, previous=second)
    native_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", {
        **settings.PLUGIN_TRUSTED_PUBLISHERS, "sample": native_key.public_key().public_bytes_raw().hex(),
    })
    package.write_bytes(build(ROOT / "preview", native_key))
    with pytest.raises(ValueError, match="declarative plugins only"):
        stage_catalogue(candidates, tmp_path / "native", catalogue_key, reviewer)


@pytest.mark.asyncio
async def test_process_worker_follows_committed_selection_and_restores_it_after_restart(
    committed_database, monkeypatch, tmp_path,
):
    import asyncio
    import sys
    from types import SimpleNamespace

    from sqlalchemy import func

    from app.llm.provider_catalog import get_provider_profile
    from app.plugin import runtime, service
    from plugins.sample.package import build
    from scripts import process_worker

    key = Ed25519PrivateKey.generate()
    publishers = {"fixture": key.public_key().public_bytes_raw().hex()}
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", publishers)
    monkeypatch.setattr(settings, "PLUGIN_EXECUTABLE_PUBLISHERS", ["fixture"])
    monkeypatch.setattr(type(settings), "APP_VERSION", "0.2.0")
    monkeypatch.setenv("PLUGIN_TRUSTED_PUBLISHERS", json.dumps(publishers))
    monkeypatch.setenv("PLUGIN_EXECUTABLE_PUBLISHERS", '["fixture"]')
    async with get_db_session() as db:
        database = await db.scalar(select(func.current_database()))
    monkeypatch.setenv("POSTGRES_DB", database)
    launcher = tmp_path / "worker"
    launcher.write_text(f"#!{sys.executable}\n"
        "import asyncio, sys\n"
        "from core import settings\n"
        "type(settings).APP_VERSION = '0.2.0'\n"
        "from scripts.process_worker import run_worker\n"
        "asyncio.run(run_worker(int(sys.argv[-1])))\n")
    launcher.chmod(0o700)
    monkeypatch.setattr(process_worker, "sys", SimpleNamespace(executable=str(launcher)))

    code = "fixture.worker-profile"
    names = {"fr": "Profil synthétique", "en": "Synthetic profile"}
    (tmp_path / "manifest.json").write_text(json.dumps({
        "format_version": 2, "code": code, "version": "1.0.0", "label": names, "description": names,
        "minimum_galaris_version": "0.1.0", "maximum_galaris_version_exclusive": "1.0.0",
        "contributions": [{"family": "llm_provider", "code": code, "label": names, "contract_version": 1}],
    }))
    (tmp_path / "backend").mkdir()
    (tmp_path / f"backend/{code}.py").write_text("from app.llm.provider_facade import ProviderProfile\n"
        "def plugin_provider(context):\n"
        f"    return ProviderProfile('{code}', 'Synthetic profile', 'openai_compatible', 'api_key', "
        "'https://synthetic.invalid/v1', None, '', 'smart_toy', 'solaire-blue')\n")
    archive = build(tmp_path, key)
    bundle = read_bundle(archive)
    worker = process_worker.ProcessWorker()

    async def wait_for_generation(expected):
        async with asyncio.timeout(15):
            while worker.plugin_generation != expected:
                assert worker.is_running()
                await asyncio.sleep(0.1)

    async with get_db_session():
        await service.restore_executable_plugins()
        await service.install(bundle, archive, bundle.digest, False, service.host_identity())
    empty = runtime.generation_fingerprint()
    try:
        async with asyncio.timeout(30):
            await worker.start()
        assert worker.plugin_generation == empty
        async with get_db_session():
            await service.change_state(code, "1.0.0", "activate", service.host_identity())
        selected = runtime.generation_fingerprint()
        assert selected != empty and get_provider_profile(code) is not None
        await wait_for_generation(selected)

        previous_pid = worker.process.pid
        await worker.stop()
        async with asyncio.timeout(30):
            await worker.start()
        assert worker.process.pid != previous_pid
        assert worker.plugin_generation == selected

        async with get_db_session():
            await service.change_state(code, "1.0.0", "deactivate", service.host_identity())
            await service.change_state(code, "1.0.0", "remove", service.host_identity())
        assert get_provider_profile(code) is None
        await wait_for_generation(empty)
    finally:
        await worker.stop()
        async with get_db_session():
            await service.change_state(code, "1.0.0", "deactivate", service.host_identity())


@pytest.mark.asyncio
async def test_executable_archive_publishes_both_entry_points_and_keeps_documents_on_removal(
    client, monkeypatch, tmp_path, memory_storage, diagnostic_directory,
):
    from types import SimpleNamespace

    import httpx
    from app.document import formats
    from app.llm import provider_catalog
    from app.plugin import runtime
    import plugin_composition
    from plugins.sample.package import build

    monkeypatch.setattr(runtime, "_active", {})
    monkeypatch.setattr(plugin_composition, "_loaded", {})
    monkeypatch.setattr(provider_catalog, "_plugin_providers", {})
    monkeypatch.setattr(formats, "_plugin_registry", formats.DocumentFormatRegistry())
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", {"example": key.public_key().public_bytes_raw().hex()})
    monkeypatch.setattr(type(settings), "APP_VERSION", "0.2.0")
    name = {"fr": "Exemple binaire", "en": "Binary sample"}
    manifest = {
        "format_version": 2, "code": "example.binary", "version": "1.0.0", "label": name, "description": name,
        "minimum_galaris_version": "0.1.0", "maximum_galaris_version_exclusive": "1.0.0",
        "contributions": [{"family": "document_format", "code": "example.binary", "label": name,
                           "contract_version": 1, "version": 1},
                          {"family": "llm_provider", "code": "example.binary.ai", "label": name, "contract_version": 1}],
    }
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    backend = tmp_path / "backend/example.binary.py"
    backend.write_text('''from app.document import DocumentFormatDefinition
def plugin_format(_context):
    assert _context.endpoints["example.worker"] == "http://worker.example.test"
    return DocumentFormatDefinition("example.binary", "application/octet-stream", "", "description",
        lambda _: None, lambda _: "", provider="example.binary", storage_kind="file", initial_binary=b"fixture",
        validate_binary=lambda _: None, surfaces=frozenset({"editor"}))
''')
    browser_code = 'export function createFormat() { return {}; }'
    qualification_errors = []

    async def verify_document_modules(bundle):
        if qualification_errors:
            raise ValueError("Synthetic Chromium module failure")
        assert bundle.assets["frontend/example.binary.mjs"] == browser_code.encode()

    monkeypatch.setattr(runtime, "verify_document_modules", verify_document_modules)
    (tmp_path / "frontend/example.binary.mjs").write_text(browser_code)
    (tmp_path / "backend/example.binary.ai.py").write_text('''from app.llm.provider_facade import ProviderProfile
def plugin_provider(_context):
    return ProviderProfile("example.binary.ai", "Synthetic provider", "openai_compatible", "api_key",
        "https://synthetic.invalid/v1", None, "", "smart_toy", "solaire-blue")
''')
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    archive = build(tmp_path, key)
    admin = await _login(client, "PLUGIN_EDIT", "DOCUMENT_EDIT")
    report = await _preview(client, admin, archive)
    assert report["compatibility"] == "native_publisher_required" and not report["can_force"]
    assert (await _install(client, admin, archive, report)).status_code == 409
    monkeypatch.setattr(settings, "PLUGIN_EXECUTABLE_PUBLISHERS", ["example"])
    manifest["python_requirements"] = ["synthetic-nonexistent-distribution==1"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    blocked = await _preview(client, admin, build(tmp_path, key))
    assert blocked["compatibility"] == "missing_dependency" and not blocked["can_force"]
    manifest.pop("python_requirements")
    manifest["runtime_requirements"] = [{"code": "example.worker", "image": "registry.invalid/worker@sha256:" + "a" * 64}]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    unconfigured = await _preview(client, admin, build(tmp_path, key))
    assert unconfigured["compatibility"] == "runtime_unconfigured" and not unconfigured["can_force"]
    monkeypatch.setattr(settings, "PLUGIN_RUNTIME_BINDINGS", {"example.worker": {
        "image": manifest["runtime_requirements"][0]["image"], "url": "http://worker.example.test",
    }})
    online = False

    def health(request):
        assert str(request.url) == "http://worker.example.test/health"
        return httpx.Response(200 if online else 503)

    monkeypatch.setattr(runtime, "httpx", SimpleNamespace(
        AsyncClient=lambda **options: httpx.AsyncClient(transport=httpx.MockTransport(health), **options),
    ))
    archive = build(tmp_path, key)
    report = await _preview(client, admin, archive)
    assert (await _install(client, admin, archive, report)).status_code == 200
    asset = f"/api/plugins/assets/{report['digest']}/example.binary.mjs"
    assert (await client.get(asset)).status_code == 404
    assert (await _change(client, admin, report, "activate")).status_code == 409
    assert (await client.get(asset)).status_code == 404
    online = True
    assert (await _change(client, admin, report, "activate")).status_code == 200
    profile = provider_catalog.get_provider_profile("example.binary.ai")
    assert profile is not None and profile.provider_type == "openai_compatible"
    response = await client.get(asset)
    assert response.status_code == 200 and response.text == browser_code
    assert response.headers["content-type"].startswith("text/javascript")
    catalogue = await client.get("/api/documents/formats", headers=admin)
    [declaration] = [item for item in catalogue.json() if item["code"] == "example.binary"]
    assert declaration["plugin_editor"]["module_url"] == asset
    user = await client.get("/api/auth/me", headers=admin)
    editor = {**admin, "X-Editorial-Profile-Version": "1"}
    created = await client.post("/api/documents", headers=editor, json={"owner_kind": "user", "owner_id": user.json()["id"],
        "title": "Synthetic archive document", "document_format": "example.binary"})
    assert created.status_code == 201, created.text
    path = "/api/documents/" + created.json()["id"]
    saved = await client.patch(path, headers=editor, json={"expected_revision": 1, "payload": {"base64": "c2F2ZWQ="}})
    assert saved.status_code == 200 and saved.json()["revision"] == 2, saved.text

    manifest.pop("runtime_requirements")
    manifest["version"] = "2.0.0"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    backend.write_text("def invalid syntax")
    broken_archive = build(tmp_path, key)
    broken = await _preview(client, admin, broken_archive)
    assert (await _install(client, admin, broken_archive, broken)).status_code == 200
    failed = await _change(client, admin, broken, "activate")
    assert failed.status_code == 409 and failed.json()["detail"] == "activation_error"
    assert (await client.get(asset)).status_code == 200
    reports = [json.loads(path.read_text()) for path in diagnostic_directory.glob("update-*.json")]
    [failure] = [report for report in reports if report["details"]["plugin_version"] == "2.0.0"]
    assert failure["details"] == {"command": "plugin:activate", "stage": "prepare_registries",
                                  "plugin_code": "example.binary", "plugin_version": "2.0.0",
                                  "archive_fingerprint": broken["digest"][:16]}
    assert failure["causes"][0]["type"] == "SyntaxError"
    assert failure["causes"][0]["locations"]
    detail = await client.get("/api/plugins/example.binary", headers=admin)
    assert detail.json()["events"][0]["operation"] == "activation_error"
    manifest["version"] = "3.0.0"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    backend.write_text("from app.document import DocumentFormatDefinition\n"
        "def plugin_format(_context):\n"
        "    return DocumentFormatDefinition('example.binary', 'application/octet-stream', '', 'description', "
        "lambda _: None, lambda _: '', provider='example.binary', storage_kind='file', "
        "initial_binary=b'fixture', validate_binary=lambda _: None, surfaces=frozenset({'editor'}))\n")
    browser_failure_archive = build(tmp_path, key)
    browser_failure = await _preview(client, admin, browser_failure_archive)
    assert (await _install(client, admin, browser_failure_archive, browser_failure)).status_code == 200
    qualification_errors.append("load")
    failed = await _change(client, admin, browser_failure, "activate")
    qualification_errors.clear()
    assert (failed.status_code, failed.json()["detail"]) == (409, "activation_error")
    assert (await client.get(asset)).status_code == 200
    reports = [json.loads(path.read_text()) for path in diagnostic_directory.glob("update-*.json")]
    [failure] = [report for report in reports if report["details"]["plugin_version"] == "3.0.0"]
    assert failure["details"]["stage"] == "verify_browser_modules"
    from core.database import get_db_session
    from app.plugin.facade import restore_executable_plugins
    async with get_db_session():
        await restore_executable_plugins()
    assert (await client.get(asset)).status_code == 200

    online = False
    async with get_db_session():
        await restore_executable_plugins()
    detail = await client.get("/api/plugins/example.binary", headers=admin)
    assert detail.status_code == 200, detail.text
    [selected] = [release for release in detail.json()["releases"] if release["selected"]]
    assert selected["manifest"]["version"] == "1.0.0" and not selected["active"]
    reports = [json.loads(path.read_text()) for path in diagnostic_directory.glob("update-*.json")]
    [startup] = [report for report in reports if report["details"]["command"] == "plugin:startup"]
    assert startup["details"]["stage"] == "probe_dependencies"
    assert "HTTP 503" in startup["causes"][0]["message"]
    assert (await client.get(asset)).status_code == 404
    assert provider_catalog.get_provider_profile("example.binary.ai") is None
    assert (await client.get(f"{path}/source", headers=editor)).content == b"saved"
    assert (await client.get(f"{path}/source?revision=1", headers=editor)).content == b"fixture"

    online = True
    retried = await _change(client, admin, report, "activate")
    assert retried.status_code == 200 and retried.json()["active"], retried.text
    assert (await client.get(asset)).status_code == 200
    assert provider_catalog.get_provider_profile("example.binary.ai") is not None

    monkeypatch.setattr(settings, "APP_ENV", "dev")
    monkeypatch.setattr(type(settings), "APP_VERSION", "feature/plugins")
    forced = await _preview(client, admin, archive)
    renewed = await _install(client, admin, archive, forced, force=True)
    assert renewed.status_code == 200 and not renewed.json()["selected"], renewed.text
    assert (await client.get(asset)).status_code == 404
    assert provider_catalog.get_provider_profile("example.binary.ai") is None
    assert (await _change(client, admin, forced, "activate")).json()["active"]

    assert (await _change(client, admin, forced, "deactivate")).status_code == 200
    assert (await _change(client, admin, forced, "remove")).status_code == 200
    assert provider_catalog.get_provider_profile("example.binary.ai") is None
    assert (await client.get(asset)).status_code == 404
    assert (await client.get(f"{path}/source", headers=editor)).content == b"saved"
    assert (await client.get(f"{path}/source?revision=1", headers=editor)).content == b"fixture"


@pytest.mark.asyncio
async def test_signed_protocol_uses_standard_service_and_account_resolution(client, monkeypatch):
    from pathlib import Path

    import httpx
    import plugin_composition
    from app.agent.models import Agent, Title
    from app.connection import connection_service
    from app.file_share import ResourceContext, resource_info, resource_read, resource_list
    from app.file_share import bridges
    from app.plugin import runtime
    from app.services.connection_diagnostics import test_saved_connection
    from plugins.sample import __file__ as samples_package
    from plugins.sample.package import build

    monkeypatch.setattr(runtime, "_active", {})
    monkeypatch.setattr(plugin_composition, "_loaded", {})
    monkeypatch.setattr(bridges, "_plugin_bridges", {})
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", {"sample": key.public_key().public_bytes_raw().hex()})
    monkeypatch.setattr(settings, "PLUGIN_EXECUTABLE_PUBLISHERS", ["sample"])
    monkeypatch.setattr(type(settings), "APP_VERSION", "0.3.2")

    async def synthetic_storage(_transport, request):
        assert request.url.path == "/api/plugin-samples/storage/note.txt"
        values = {"Bearer synthetic-first": "Account one", "Bearer synthetic-second": "Account two"}
        if (value := values.get(request.headers.get("authorization", ""))) is None:
            return httpx.Response(401)
        return httpx.Response(200, headers={"content-length": str(len(value))},
            content=value if request.method == "GET" else b"")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", synthetic_storage)
    headers = await _login(client, "PLUGIN_EDIT", "SERVICE_EDIT")
    user = await client.get("/api/auth/me", headers=headers)
    assert user.is_success, user.text
    async with get_db_session() as db:
        title = Title(label="Synthetic storage qualification", gender="X")
        db.add(title)
        await db.flush()
        agents = [Agent(user_id=user.json()["id"], title_id=title.id, code=f"file-fixture-{uuid4().hex}",
            first_name="Synthetic", last_name="Storage", agent_driver="internal") for _ in range(2)]
        db.add_all(agents)
        await db.flush()
        first, second = [ResourceContext(agent.id, "internal") for agent in agents]
    archive = build(Path(samples_package).with_name("file_share"), key)
    declaration = await _preview(client, headers, archive)
    assert declaration["compatibility"] == "supported"
    assert (await _install(client, headers, archive, declaration)).is_success

    async def advertised():
        response = await client.get("/api/services/capabilities", headers=headers)
        assert response.is_success, response.text
        return {protocol["value"] for item in response.json() for protocol in item["protocols"]}

    selection = "sample.storage.file_share"
    assert selection not in await advertised()
    assert (await _change(client, headers, declaration, "activate")).is_success
    assert selection in await advertised()
    catalogue = await client.get("/api/services/catalog", headers=headers)
    preset = next(item["definition"] for item in catalogue.json()["entries"] if item["definition"]["code"] == "sample-storage")
    copied = await client.post("/api/services", headers=headers, json=preset)
    assert copied.status_code == 201, copied.text
    service_id = copied.json()["id"]

    file_uri = "sample-storage://note.txt"
    async with get_db_session():
        account = await connection_service.create_connection(service_id, first.agent_id)
        account_id = account.id
        await connection_service.set_param(account_id, "token", "synthetic-first")
        assert (await test_saved_connection(account_id)).status == "success"
        assert [entry.uri for entry in (await resource_list(first, "sample-storage://")).entries] == [file_uri]
        assert (await resource_read(first, file_uri)).content == "Account one"
        assert "write" not in (await resource_info(first, file_uri)).capabilities
        with pytest.raises(ValueError, match="sample-storage"):
            await resource_read(second, file_uri)
        other = await connection_service.create_connection(service_id, second.agent_id)
        await connection_service.set_param(other.id, "token", "synthetic-second")
        assert (await resource_read(second, file_uri)).content == "Account two"

    for action in ("deactivate", "remove"):
        assert (await _change(client, headers, declaration, action)).is_success
    assert selection not in await advertised()
    assert (await client.get(f"/api/services/{service_id}", headers=headers)).json()["capabilities"] == [selection]
    async with get_db_session():
        assert (await test_saved_connection(account_id)).status == "error"
    assert (await _install(client, headers, archive, declaration)).is_success
    assert (await _change(client, headers, declaration, "activate")).is_success
    async with get_db_session():
        assert (await resource_read(first, file_uri)).content == "Account one"
        assert (await resource_read(second, file_uri)).content == "Account two"
    assert (await _change(client, headers, declaration, "deactivate")).is_success


@pytest.mark.asyncio
async def test_catalogue_reuses_signed_archive_preview_and_install(client, bundle_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PLUGIN_CATALOG_DIRECTORY", tmp_path)
    archive = bundle_factory()
    (tmp_path / "valid.zip").write_bytes(archive)
    (tmp_path / "invalid.zip").write_bytes(bundle_factory(tampered=True))
    reader = await _login(client, "PLUGIN_ACCESS")
    assert (await client.get("/api/plugins/catalog", headers=reader)).status_code == 403
    editor = await _login(client, "PLUGIN_EDIT")
    result = await client.get("/api/plugins/catalog", headers=editor)
    assert result.status_code == 200, result.text
    [entry] = result.json()
    assert entry == await _preview(client, editor, archive)
    downloaded = await client.get(f"/api/plugins/catalog/{entry['digest']}", headers=editor)
    assert downloaded.status_code == 200 and downloaded.content == archive
    installed = await _install(client, editor, downloaded.content, entry)
    assert installed.status_code == 200 and not installed.json()["active"]


@pytest.mark.asyncio
async def test_remote_catalogue_checks_archive_series_expiry_and_revocation(client, bundle_factory, monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone

    import httpx
    from app.plugin import catalog, remote_catalog

    clock = initial = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock if tz is not None else clock.replace(tzinfo=None)

    monkeypatch.setattr(catalog, "datetime", Clock)
    monkeypatch.setattr(remote_catalog, "datetime", Clock)
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(settings, "PLUGIN_CATALOG_DIRECTORY", tmp_path)
    monkeypatch.setattr(settings, "PLUGIN_CATALOG_REMOTE_URL", "https://catalogue.example.test/plugins/")
    monkeypatch.setattr(settings, "PLUGIN_CATALOG_REMOTE_PUBLIC_KEY", key.public_key().public_bytes_raw().hex())
    online = True
    body = b""
    signature = b""
    content = bundle_factory()
    remote_bundle = read_bundle(content)
    archive_bytes = content
    local = bundle_factory("1.1.0", code="synthetic-local")
    (tmp_path / "local.zip").write_bytes(local)
    expiry = clock + timedelta(hours=1)

    def publish(sequence, revoked=()):
        nonlocal body, signature
        body = json.dumps({"format_version": 1, "sequence": sequence, "issued_at": clock.isoformat(),
            "expires_at": expiry.isoformat(), "revoked": list(revoked), "releases": [{
                "manifest": remote_bundle.manifest.model_dump(mode="json"),
                "digest": remote_bundle.digest, "signer": remote_bundle.signer,
            }]}).encode()
        signature = key.sign(body)

    def publisher(_transport, request):
        assert request.url.host == "catalogue.example.test"
        if not online:
            raise httpx.ConnectError("Synthetic publisher outage")
        assets = {"index.sig": signature, "index.json": body, f"archives/{remote_bundle.digest}.zip": archive_bytes}
        return httpx.Response(200, stream=httpx.ByteStream(assets[request.url.path.removeprefix("/plugins/")]))

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", publisher)
    admin = await _login(client, "PLUGIN_EDIT")
    index_path = "/api/plugins/catalog"
    remote_path = f"{index_path}/{remote_bundle.digest}"

    async def versions():
        result = await client.get(index_path, headers=admin)
        assert result.is_success, result.text
        return {record["manifest"]["version"] for record in result.json()}

    publish(1)
    signature = b"x" * 64
    assert await versions() == {"1.1.0"}
    publish(2)
    assert await versions() == {"1.0.0", "1.1.0"}
    assert (await client.get(remote_path, headers=admin)).content == content
    report = await _preview(client, admin, content)
    assert (await _install(client, admin, content, report)).is_success
    assert (await _change(client, admin, report, "activate")).json()["active"]
    archive_bytes = local
    assert (await client.get(remote_path, headers=admin)).status_code == 503
    archive_bytes = content

    online = False
    assert await versions() == {"1.0.0", "1.1.0"}
    clock = expiry + timedelta(seconds=1)
    assert await versions() == {"1.1.0"}
    assert (await client.get(remote_path, headers=admin)).status_code == 404
    clock = initial
    online = True

    publish(3, revoked=(remote_bundle.digest,))
    assert await versions() == {"1.1.0"}
    assert (await _change(client, admin, report, "activate")).json() == {"detail": "revoked"}
    from app.plugin.facade import refresh_catalogue_revocations

    online = False
    clock = expiry + timedelta(seconds=1)
    async with get_db_session():
        await refresh_catalogue_revocations()
    async with get_db_session():
        await refresh_catalogue_revocations()
    detail = (await client.get("/api/plugins/example.studio", headers=admin)).json()
    [release] = detail["releases"]
    assert release["installed"] and not release["selected"] and not release["active"]
    assert release["compatibility"] == "revoked"
    assert [event["operation"] for event in detail["events"]].count("revoked") == 1
    clock = initial
    online = True
    publish(2)
    assert await versions() == {"1.1.0"}
    assert (await client.get(remote_path, headers=admin)).status_code == 404
    assert (await _change(client, admin, report, "remove")).is_success
    monkeypatch.setattr(settings, "PLUGIN_CATALOG_REMOTE_URL", "")
    monkeypatch.setattr(settings, "PLUGIN_CATALOG_REMOTE_PUBLIC_KEY", "")
    assert (await _install(client, admin, content, report)).json() == {"detail": "revoked"}


@pytest.mark.asyncio
async def test_signed_data_template_can_be_imported_and_keeps_the_copy_after_removal(client, monkeypatch):
    from plugins.sample.inventory import ROOT
    from plugins.sample.package import build

    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", {"sample": key.public_key().public_bytes_raw().hex()})
    monkeypatch.setattr(settings, "PLUGIN_EXECUTABLE_PUBLISHERS", [])
    monkeypatch.setattr(type(settings), "APP_VERSION", "0.2.0")
    archive = build(ROOT / "data", key)
    admin = await _login(client, "PLUGIN_EDIT", "DOCUMENT_EDIT")
    report = await _preview(client, admin, archive)
    uri = "/api/plugins/sample.data/templates/sample.data"
    assert report["compatibility"] == "supported"
    assert (await _install(client, admin, archive, report)).status_code == 200
    assert (await client.get(uri, headers=admin)).status_code == 404
    assert (await _change(client, admin, report, "activate")).status_code == 200
    template = await client.get(uri, headers=admin)
    assert template.status_code == 200 and template.json()[0]["sku"] == "DEMO-001"
    owner = (await client.get("/api/auth/me", headers=admin)).json()["id"]
    imported = await client.post("/api/documents/import", headers={**admin, "X-Editorial-Profile-Version": "1"},
        files={"file": ("sample.data.json", template.content, "application/json")},
        data={"data": json.dumps({"owner_kind": "user", "owner_id": owner, "title": "Synthetic imported copy", "document_format": "data"})})
    assert imported.status_code == 201, imported.text
    assert (await _change(client, admin, report, "deactivate")).status_code == 200
    assert (await _change(client, admin, report, "remove")).status_code == 200
    assert (await client.get(uri, headers=admin)).status_code == 404
    copy = await client.get(f"/api/documents/{imported.json()['id']}/source", headers=admin)
    assert copy.status_code == 200 and copy.json() == template.json()


@pytest.mark.asyncio
async def test_declarative_plugin_lifecycle_preserves_local_service(client, bundle_factory, diagnostic_directory):
    archive = bundle_factory()
    assert (await client.get("/api/plugins")).status_code == 401
    reader = await _login(client, "PLUGIN_ACCESS")
    assert (await client.get("/api/plugins", headers=reader)).status_code == 200
    assert (await client.post("/api/plugins/preview", headers=reader, files=_upload(archive))).status_code == 403

    admin = await _login(client, "PLUGIN_EDIT", "SERVICE_EDIT")
    report = await _preview(client, admin, archive)
    assert report["compatibility"] == "supported"
    assert (await _install(client, admin, archive, {**report, "digest": "a" * 64})).status_code == 409
    for _ in range(2):
        installed = await _install(client, admin, archive, report)
        assert installed.status_code == 200, installed.text
        assert installed.json()["installed"] and not installed.json()["active"]
    collision = bundle_factory(code="synthetic-other")
    collision_report = await _preview(client, admin, collision)
    assert (await _install(client, admin, collision, collision_report)).json()["detail"] == "version_conflict"
    assert await _preset(client, admin) is None

    activated = await _change(client, admin, report, "activate")
    assert activated.status_code == 200 and activated.json()["active"], activated.text
    preset = await _preset(client, admin)
    assert preset and preset["catalog"]["plugin_code"] == "example.studio"
    copy = await client.post("/api/services", headers=admin, json={**preset, "label": "Local service name"})
    assert copy.status_code == 201, copy.text
    copy_id = copy.json()["id"]

    v2 = bundle_factory("2.0.0")
    v2_report = await _preview(client, admin, v2)
    assert (await _install(client, admin, v2, v2_report)).status_code == 200

    def interrupt_activation(session, *_):
        if any(isinstance(item, PluginEvent) and item.operation == "activated" for item in session.new):
            raise RuntimeError("synthetic interruption before the activation receipt")

    event.listen(Session, "before_flush", interrupt_activation)
    try:
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            await _change(client, admin, v2_report, "activate")
    finally:
        event.remove(Session, "before_flush", interrupt_activation)
    assert (await _preset(client, admin))["catalog"]["plugin_version"] == "1.0.0"
    [diagnostic] = [json.loads(path.read_text()) for path in diagnostic_directory.glob("update-*.json")]
    assert diagnostic["details"]["stage"] == "commit_selection"
    assert "synthetic interruption" in diagnostic["causes"][0]["message"]

    assert (await _change(client, admin, v2_report, "activate")).status_code == 200
    assert (await _preset(client, admin))["catalog"]["plugin_version"] == "2.0.0"
    assert (await _change(client, admin, report, "activate")).status_code == 200
    assert (await _preset(client, admin))["catalog"]["plugin_version"] == "1.0.0"

    assert (await _change(client, admin, report, "remove")).status_code == 409
    assert (await _change(client, admin, report, "deactivate")).status_code == 200
    assert (await _change(client, admin, report, "remove")).status_code == 200
    assert await _preset(client, admin) is None
    stored = await client.get(f"/api/services/{copy_id}", headers=admin)
    assert stored.status_code == 200 and stored.json()["label"] == "Local service name"
    detail = (await client.get("/api/plugins/example.studio", headers=admin)).json()
    assert sum(event["operation"] == "installed" for event in detail["events"]) == 2
    assert len((await client.get("/api/plugins", headers=admin)).json()) == 1


@pytest.mark.asyncio
async def test_force_is_bound_to_development_build_and_never_overrides_trust(client, bundle_factory, monkeypatch):
    admin = await _login(client, "PLUGIN_EDIT", "SERVICE_EDIT")
    archive = bundle_factory()
    monkeypatch.setattr(type(settings), "APP_VERSION", "feature/plugins")
    monkeypatch.setattr(settings, "APP_ENV", "pp")
    report = await _preview(client, admin, archive)
    assert report["compatibility"] == "host_version" and not report["can_force"]
    assert (await _install(client, admin, archive, report, force=True)).status_code == 403

    monkeypatch.setattr(settings, "APP_ENV", "dev")
    report = await _preview(client, admin, archive)
    assert report["can_force"]
    assert (await _install(client, admin, archive, report)).status_code == 409
    assert (await _install(client, admin, archive, report, force=True)).status_code == 200
    assert (await _change(client, admin, report, "activate")).status_code == 200
    assert await _preset(client, admin)

    monkeypatch.setattr(type(settings), "APP_BUILD_REVISION", "b" * 40)
    assert await _preset(client, admin) is None
    assert (await _change(client, admin, report, "activate")).status_code == 409
    monkeypatch.setattr(settings, "PLUGIN_TRUSTED_PUBLISHERS", {})
    assert (await _install(client, admin, archive, report, force=True)).json()["detail"] == "untrusted_publisher"
