from __future__ import annotations

from pathlib import Path

from scripts.frontend_architecture_contracts import (
    FRONTEND_BASELINE_PATH,
    build_frontend_architecture_baseline,
    check_frontend_architecture_contracts,
    serialize_frontend_architecture_baseline,
)
from scripts.project_context import (
    frontend_dependencies,
    frontend_import_specifiers,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fixture(tmp_path: Path) -> None:
    _write(
        tmp_path / "front/modules.ts",
        "export const modules = ['app/alpha', 'app/beta']\n",
    )
    _write(
        tmp_path / "front/app/alpha/index.ts",
        "export type { PublicValue } from '@/app/beta/types'\n",
    )
    _write(tmp_path / "front/app/beta/types.ts", "export type PublicValue = string\n")
    baseline = build_frontend_architecture_baseline(tmp_path)
    _write(
        tmp_path / FRONTEND_BASELINE_PATH,
        serialize_frontend_architecture_baseline(baseline),
    )


def test_frontend_import_parser_handles_static_dynamic_and_exports() -> None:
    imports = frontend_import_specifiers(
        """
import { ref } from 'vue'
import type { Task } from '@/app/task/types'
export { api } from '@/core/api'
const page = import('@/app/agent/pages/index.vue')
"""
    )

    assert imports == [
        "@/app/agent/pages/index.vue",
        "@/app/task/types",
        "@/core/api",
        "vue",
    ]


def test_frontend_dependencies_resolve_alias_and_relative_imports(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "front/app/alpha/index.ts",
        "import '@/app/beta'\nimport '../../bridge/mail/facade'\n",
    )
    _write(tmp_path / "front/app/beta/index.ts", "")
    _write(tmp_path / "front/bridge/mail/facade.ts", "")

    assert frontend_dependencies(tmp_path) == [
        {
            "source": "app/alpha",
            "target": "app/beta",
            "files": ["front/app/alpha/index.ts"],
        },
        {
            "source": "app/alpha",
            "target": "bridge/mail",
            "files": ["front/app/alpha/index.ts"],
        },
    ]


def test_frontend_contract_rejects_new_dependency_and_private_import(
    tmp_path: Path,
) -> None:
    _fixture(tmp_path)
    _write(
        tmp_path / "front/app/beta/index.ts",
        "import AlphaPanel from '@/app/alpha/components/AlphaPanel.vue'\n",
    )

    errors = check_frontend_architecture_contracts(tmp_path)

    assert "new frontend module dependency: app/beta -> app/alpha" in errors
    assert (
        "front/app/beta/index.ts: new private frontend import "
        "@/app/alpha/components/AlphaPanel.vue"
    ) in errors
    assert (
        "new or expanded frontend dependency cycle: app/alpha, app/beta"
    ) in errors


def test_frontend_contract_requires_baseline_reduction(tmp_path: Path) -> None:
    _fixture(tmp_path)
    _write(tmp_path / "front/app/alpha/index.ts", "")

    assert check_frontend_architecture_contracts(tmp_path) == [
        "front/architecture-baseline.json: remove resolved dependency "
        "app/alpha -> app/beta from baseline"
    ]
