from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.architecture_check import _contains_versioned_path, check_plans
from scripts.architecture_contracts import check_architecture_contracts
from scripts.docs_i18n_check import check_documentation_locales
from scripts.project_context import (
    DependencyEdge,
    ProjectMap,
    backend_modules,
    dependency_metrics,
    frontend_modules,
    render_markdown,
    settings_map,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_versioned_path_ignores_local_untracked_directory(tmp_path: Path) -> None:
    _write(tmp_path / ".claude/settings.local.json", "{}\n")

    with patch("scripts.architecture_check.subprocess.run") as run:
        run.return_value = Mock(returncode=0, stdout="")
        assert _contains_versioned_path(tmp_path, ".claude") is False


def test_versioned_path_rejects_tracked_legacy_directory(tmp_path: Path) -> None:
    with patch("scripts.architecture_check.subprocess.run") as run:
        run.return_value = Mock(
            returncode=0,
            stdout=".claude/settings.json\n",
        )
        assert _contains_versioned_path(tmp_path, ".claude") is True


def test_versioned_path_allows_known_local_file_without_git(tmp_path: Path) -> None:
    _write(tmp_path / ".claude/settings.local.json", "{}\n")

    with patch("scripts.architecture_check.subprocess.run") as run:
        run.return_value = Mock(returncode=127, stdout="")
        assert _contains_versioned_path(
            tmp_path,
            ".claude",
            allowed_local_files=frozenset({"settings.local.json"}),
        ) is False


def test_versioned_path_allows_known_local_file_when_git_is_missing(tmp_path: Path) -> None:
    _write(tmp_path / ".claude/settings.local.json", "{}\n")

    with patch(
        "scripts.architecture_check.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        assert _contains_versioned_path(
            tmp_path,
            ".claude",
            allowed_local_files=frozenset({"settings.local.json"}),
        ) is False


def test_plan_index_is_loaded_from_project_directory(tmp_path: Path) -> None:
    _write(
        tmp_path / "project/plans/README.md",
        "| Plan | Statut | Lecture actuelle |\n"
        "|---|---|---|\n"
        "| [active.md](active.md) | `design` | Intention active. |\n",
    )
    _write(tmp_path / "project/plans/active.md", "# Plan actif\n")

    assert check_plans(tmp_path) == []


def test_backend_modules_resolves_referenced_starred_lists(tmp_path: Path) -> None:
    _write(
        tmp_path / "back/modules.py",
        """
OPTIONAL_MODULES = ["bridge.first", "bridge.second"]
MODULES = ["app.required", *OPTIONAL_MODULES]
""".strip(),
    )

    modules = backend_modules(tmp_path)

    assert [(module["name"], module["conditional"]) for module in modules] == [
        ("app.required", False),
        ("bridge.first", True),
        ("bridge.second", True),
    ]


def test_module_capabilities_ignore_empty_local_directories(tmp_path: Path) -> None:
    """A Git snapshot without empty directories must have the same source map."""
    _write(tmp_path / "back/modules.py", 'MODULES = ["app.example"]\n')
    _write(tmp_path / "back/app/example/__init__.py", "")
    _write(tmp_path / "front/modules.ts", 'export const modules = ["app/example"]\n')
    _write(tmp_path / "front/app/example/i18n.ts", "export default {}\n")
    before = backend_modules(tmp_path), frontend_modules(tmp_path)
    directories = [
        "back/app/example/tests", "back/app/example/i18n",
        "front/app/example/components", "front/app/example/pages",
        "front/app/example/services", "front/app/example/stores",
    ]
    for directory in directories:
        (tmp_path / directory).mkdir()
    _write(tmp_path / "back/app/example/tests/__pycache__/old.pyc", "cache")

    assert (backend_modules(tmp_path), frontend_modules(tmp_path)) == before

    _write(tmp_path / "back/app/example/tests/test_example.py", "def test_example(): pass\n")
    _write(tmp_path / "back/app/example/i18n/en.py", 'translations = {}\n')
    _write(tmp_path / "front/app/example/components/Example.vue", "<template>Example</template>\n")
    _write(tmp_path / "front/app/example/pages/index.vue", "<template>Example</template>\n")
    _write(tmp_path / "front/app/example/services/example.ts", "export default {}\n")
    _write(tmp_path / "front/app/example/stores/example.ts", "export default {}\n")
    assert backend_modules(tmp_path)[0]["capabilities"] == ["i18n/", "tests/"]
    modules, pages = frontend_modules(tmp_path)
    assert modules[0]["capabilities"] == ["components", "i18n.ts", "pages", "services", "stores"]
    assert pages[0]["route_hint"] == "/example"


def test_dependency_metrics_reports_cycles_and_degrees() -> None:
    edges: list[DependencyEdge] = [
        {"source": "app.alpha", "target": "app.beta", "files": ["alpha.py"]},
        {"source": "app.beta", "target": "app.alpha", "files": ["beta.py"]},
        {"source": "app.gamma", "target": "app.alpha", "files": ["gamma.py"]},
        {"source": "app.alpha", "target": "core.database", "files": ["alpha.py"]},
    ]

    metrics = dependency_metrics(edges)

    assert metrics["domain_edges"] == 3
    assert metrics["direct_cycles"] == [["app.alpha", "app.beta"]]
    assert metrics["strongly_connected_components"] == [["app.alpha", "app.beta"]]
    assert metrics["fan_in"][0] == {
        "module": "app.alpha",
        "count": 2,
        "modules": ["app.beta", "app.gamma"],
    }


def test_documentation_locales_require_structural_parity_and_valid_links(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "docs/README.md",
        "# Documentation\n\n[English](en/guide.md)\n[Français](fr/guide.md)\n",
    )
    _write(
        tmp_path / "docs/fr/guide.md",
        '<p align="right"><strong>Français</strong> · '
        '<a href="../en/guide.md">English</a></p>\n\n'
        "# Guide\n\n[Asset](asset.txt)\n\n```text\nstable\n```\n",
    )
    _write(
        tmp_path / "docs/en/guide.md",
        '<p align="right"><a href="../fr/guide.md">Français</a> · '
        "<strong>English</strong></p>\n\n"
        "# Guide\n\n[Asset](asset.txt)\n\n```text\nstable\n```\n",
    )
    _write(tmp_path / "docs/fr/asset.txt", "stable\n")
    _write(tmp_path / "docs/en/asset.txt", "stable\n")

    assert check_documentation_locales(tmp_path) == []


def test_documentation_locales_report_a_missing_translation(tmp_path: Path) -> None:
    _write(tmp_path / "docs/README.md", "# Documentation\n")
    _write(tmp_path / "docs/fr/guide.md", "# Guide\n")
    (tmp_path / "docs/en").mkdir(parents=True)

    errors = check_documentation_locales(tmp_path)

    assert "docs/en is missing or empty" in errors
    assert "documentation file guide.md is missing from: en" in errors


def test_project_map_markdown_is_localized() -> None:
    empty_metrics = {
        "domain_edges": 0,
        "direct_cycles": [],
        "strongly_connected_components": [],
        "fan_in": [],
        "fan_out": [],
    }
    project: ProjectMap = {
        "schema_version": 3,
        "generated_by": "back/scripts/project_context.py",
        "backend": {
            "modules": [],
            "dependencies": [],
            "dependency_metrics": empty_metrics,
            "routes": [],
            "models": [],
            "mcp_tools": [],
            "privileges": [],
        },
        "frontend": {
            "modules": [],
            "dependencies": [],
            "dependency_metrics": empty_metrics,
            "pages": [],
        },
        "settings": {
            "declared": [],
            "env_example": [],
            "missing_from_env_example": [],
            "env_only": [],
        },
    }

    assert "# Cartographie générée de Galaris" in render_markdown(project, "fr")
    assert "# Generated Galaris Project Map" in render_markdown(project, "en")


def test_settings_map_includes_commented_options_and_excludes_internal_constants(tmp_path: Path) -> None:
    _write(
        tmp_path / "back/core/settings.py",
        "from typing import ClassVar\n\n"
        "class Settings:\n"
        "    APP_HOST: str = 'http://localhost'\n"
        "    APP_NAME: str = 'galaris'\n"
        "    LOG_LEVEL: str = 'INFO'\n"
        "    INTERNAL_ROOT: ClassVar[str] = '/data/internal'\n",
    )
    _write(tmp_path / ".env.example", "APP_HOST=http://localhost\n#APP_NAME=galaris\n# LOG_LEVEL=INFO\n# Other settings are internal.\n")

    assert settings_map(tmp_path) == {
        "declared": ["APP_HOST", "APP_NAME", "LOG_LEVEL"],
        "env_example": ["APP_HOST", "APP_NAME", "LOG_LEVEL"],
        "missing_from_env_example": [],
        "env_only": [],
    }


def _architecture_fixture(tmp_path: Path) -> None:
    _write(
        tmp_path / "back/modules.py",
        'MODULES = ["app.alpha", "app.beta"]\n',
    )
    _write(
        tmp_path / "back/app/alpha/__init__.py",
        "from app.beta.contracts import PublicContract\n",
    )
    _write(tmp_path / "back/app/beta/__init__.py", "")
    _write(tmp_path / "back/app/beta/contracts.py", "class PublicContract: ...\n")
    _write(
        tmp_path / "back/architecture.toml",
        """
version = 1
public_suffixes = ["contracts", "facade", "interface"]

[module."app.alpha"]
allowed_dependencies = ["app.beta"]
max_domain_fan_out = 1

[module."app.beta"]
allowed_dependencies = []
max_domain_fan_out = 0
""".strip()
        + "\n",
    )
    _write(
        tmp_path / "back/architecture-baseline.json",
        json.dumps(
            {
                "schema_version": 1,
                "private_imports": [],
                "strongly_connected_components": [],
            }
        ),
    )


def test_contracts_accept_declared_public_dependency(tmp_path: Path) -> None:
    _architecture_fixture(tmp_path)

    assert check_architecture_contracts(tmp_path) == []


def test_contracts_reject_new_private_import(tmp_path: Path) -> None:
    _architecture_fixture(tmp_path)
    _write(
        tmp_path / "back/app/alpha/__init__.py",
        "from app.beta.internal import Hidden\n",
    )

    errors = check_architecture_contracts(tmp_path)

    assert errors == [
        "back/app/alpha/__init__.py: new private cross-module import app.beta.internal"
    ]


def test_contracts_require_removed_dependency_to_lower_manifest(tmp_path: Path) -> None:
    _architecture_fixture(tmp_path)
    _write(tmp_path / "back/app/alpha/__init__.py", "")

    errors = check_architecture_contracts(tmp_path)

    assert errors == [
        "back/architecture.toml: remove unused allowed dependency app.alpha -> app.beta"
    ]


def test_contracts_require_resolved_private_import_to_lower_baseline(
    tmp_path: Path,
) -> None:
    _architecture_fixture(tmp_path)
    _write(
        tmp_path / "back/architecture-baseline.json",
        json.dumps(
            {
                "schema_version": 1,
                "private_imports": [
                    {
                        "source": "back/app/alpha/__init__.py",
                        "target": "app.beta.internal",
                    }
                ],
                "strongly_connected_components": [],
            }
        ),
    )

    errors = check_architecture_contracts(tmp_path)

    assert errors == [
        "back/architecture-baseline.json: remove resolved private import "
        "back/app/alpha/__init__.py -> app.beta.internal from baseline"
    ]


def test_contracts_reject_new_cycle_even_when_edge_is_declared(tmp_path: Path) -> None:
    _architecture_fixture(tmp_path)
    manifest = tmp_path / "back/architecture.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'allowed_dependencies = []\nmax_domain_fan_out = 0',
            'allowed_dependencies = ["app.alpha"]\nmax_domain_fan_out = 1',
        ),
        encoding="utf-8",
    )
    _write(
        tmp_path / "back/app/beta/__init__.py",
        "from app.alpha import PublicFacade\n",
    )

    errors = check_architecture_contracts(tmp_path)

    assert errors == ["new or expanded dependency cycle: app.alpha, app.beta"]
