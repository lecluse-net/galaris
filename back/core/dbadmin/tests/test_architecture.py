from __future__ import annotations

import ast
from pathlib import Path


BACK_ROOT = Path(__file__).resolve().parents[3]


def test_atlas_runtime_invocation_is_private_to_dbadmin() -> None:
    offenders: list[str] = []
    allowed_root = BACK_ROOT / "core" / "dbadmin" / "_internal"
    for root_name in ("core", "app", "bridge", "scripts"):
        for path in (BACK_ROOT / root_name).rglob("*.py"):
            if path.is_relative_to(allowed_root) or "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if any(
                    isinstance(argument, ast.Constant) and argument.value == "atlas"
                    for argument in node.args
                ):
                    offenders.append(str(path.relative_to(BACK_ROOT)))

    assert offenders == []


def test_core_dbadmin_has_no_app_or_bridge_import() -> None:
    offenders: list[str] = []
    package = BACK_ROOT / "core" / "dbadmin"
    for path in package.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names.append(node.module)
            if any(name == "app" or name.startswith(("app.", "bridge.")) for name in names):
                offenders.append(str(path.relative_to(BACK_ROOT)))

    assert offenders == []


def test_legacy_upgrade_script_is_gone() -> None:
    assert not (BACK_ROOT / "scripts" / "upgrade.py").exists()


def test_runtime_lifespan_does_not_reconcile_reference_data() -> None:
    source = (BACK_ROOT / "main.py").read_text(encoding="utf-8")

    assert "params_service.sync()" not in source
    assert "sync_mandatory_tools()" not in source
    assert "profile_service.ensure_default_profile()" not in source
    assert "skill_service.sync_from_disk()" not in source


def test_modules_contribute_data_sources_not_procedural_datasets() -> None:
    offenders: list[str] = []
    for path in BACK_ROOT.rglob("dbadmin.py"):
        if path.is_relative_to(BACK_ROOT / "core" / "dbadmin"):
            continue
        source = path.read_text(encoding="utf-8")
        if ".register_dataset(" in source:
            offenders.append(str(path.relative_to(BACK_ROOT)))

    assert offenders == []
