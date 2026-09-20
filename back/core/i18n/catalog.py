"""Lazy aggregation of module-owned i18n catalogs.

Like the frontend catalog loader, each backend module that needs translated messages exposes an
``i18n`` package publishing ``messages = {"en": {...}, "fr": {...}}``. Catalog discovery occurs
on first access rather than import because importing a module package may itself depend on
``core.i18n``. Model prompts are deliberately outside this translation catalog.
"""

from __future__ import annotations

import runpy
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from loguru import logger

# Languages supported by both backend and frontend.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "fr", "zh")

# Backend root: parent of the ``core`` package.
_BACK_ROOT = Path(__file__).resolve().parents[2]
# Package namespaces scanned for nested ``i18n`` packages.
_NAMESPACES = ("app", "core", "bridge")

def _discover_packages() -> list[str]:
    """Return dotted paths for module-level ``i18n`` packages found on disk.

    The two-level glob finds nested packages such as ``app.agent.i18n`` without collecting this
    engine package itself.
    """
    found: list[str] = []
    for namespace in _NAMESPACES:
        namespace_dir = _BACK_ROOT / namespace
        if not namespace_dir.is_dir():
            continue
        for i18n_dir in sorted(namespace_dir.glob("*/i18n")):
            if (i18n_dir / "__init__.py").is_file():
                found.append(f"{namespace}.{i18n_dir.parent.name}.i18n")
    return found


def _load_language_file(package_name: str, lang: str) -> dict[str, Any]:
    """Load one pure-data catalog without importing its parent domain package.

    Importing ``app.lab.i18n`` through Python's normal package mechanism first executes
    ``app.lab.__init__``. During model bootstrap that can create a circular import and make a
    valid catalog disappear from the memoized aggregate. Language files are deliberately
    dependency-free, so executing the individual file avoids domain side effects entirely.
    """

    path = _BACK_ROOT.joinpath(*package_name.split("."), f"{lang}.py")
    namespace = runpy.run_path(
        str(path),
        run_name=f"_galaris_i18n_{package_name.replace('.', '_')}_{lang}",
    )
    section = namespace.get("default")
    if not isinstance(section, dict):
        raise TypeError(f"{path} does not expose a `default` dictionary")
    return cast(dict[str, Any], section)


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Deep-copy and merge ``source`` into ``target``.

    Nested dictionaries must never be aliased with module catalogs, otherwise later catalog
    merges could mutate messages owned by another module.
    """
    for key, value in source.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            _deep_merge(cast(dict[str, Any], existing), cast(dict[str, Any], value))
        elif isinstance(value, dict):
            target[key] = {}
            _deep_merge(target[key], cast(dict[str, Any], value))
        else:
            target[key] = value


@lru_cache(maxsize=1)
def get_messages() -> dict[str, dict[str, Any]]:
    """Return the memoized merged catalog as ``{language: messages}``."""
    messages: dict[str, dict[str, Any]] = {lang: {} for lang in SUPPORTED_LANGUAGES}
    for dotted in _discover_packages():
        for lang in SUPPORTED_LANGUAGES:
            if not _BACK_ROOT.joinpath(*dotted.split("."), f"{lang}.py").is_file():
                continue
            try:
                section = _load_language_file(dotted, lang)
            except Exception as exc:  # One broken catalog must not disable the i18n engine.
                logger.warning(f"i18n: failed to load catalog {dotted}.{lang}: {exc}")
                continue
            _deep_merge(messages[lang], section)
    return messages
