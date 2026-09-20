"""Tests for the backend internationalization core."""

import importlib
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing import Any, cast

import pytest

from core.i18n import SUPPORTED_LANGUAGES, i18n_service
from core.i18n import normalize_language, render_prompt, t
from core.i18n import catalog
from core.params.runtime_settings import runtime_settings


# =============================================================================
# render_prompt — replace ${name} without interpreting unrelated braces
# =============================================================================

def test_render_prompt_only_replaces_named_placeholders():
    prompt = render_prompt(
        'Agent=${agent_name}; JSON={"price": "$5"}; unknown=${unknown}',
        agent_name="Ada",
    )

    assert prompt == 'Agent=Ada; JSON={"price": "$5"}; unknown=${unknown}'


def test_render_prompt_none_value_becomes_empty():
    prompt = render_prompt("a=${a}|b=${b}", a=None, b="x")

    assert prompt == "a=|b=x"


def test_render_prompt_removes_empty_optional_section_entirely():
    prompt = render_prompt(
        "Before\n<plan-shared-context>\n${shared_context}\n</plan-shared-context>\nAfter",
        optional_sections={"shared_context": "plan-shared-context"},
        shared_context="  ",
    )

    assert prompt == "Before\nAfter"


def test_render_prompt_keeps_non_empty_optional_section():
    prompt = render_prompt(
        "<plan-shared-context>\n${shared_context}\n</plan-shared-context>",
        optional_sections={"shared_context": "plan-shared-context"},
        shared_context="Previous result",
    )

    assert prompt == "<plan-shared-context>\nPrevious result\n</plan-shared-context>"


# =============================================================================
# t / lookup
# =============================================================================

def test_t_resolves_dotted_key():
    assert "{steps}" in t("prompts.planner_notice", "fr")
    assert "{steps}" in t("prompts.planner_notice", "en")


def test_t_unknown_key_returns_key():
    assert t("prompts.does_not_exist", "fr") == "prompts.does_not_exist"


def test_t_unsupported_lang_falls_back_to_default():
    # Unsupported languages fall back to the configured default.
    assert t("prompts.planner_notice", "de") == t("prompts.planner_notice", None)


def test_default_language_uses_runtime_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_settings, "DEFAULT_LANGUAGE", "fr")

    assert i18n_service.default_language() == "fr"


def test_normalize_language_accepts_locale_and_uses_runtime_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_settings, "DEFAULT_LANGUAGE", "fr")

    assert normalize_language("FR-fr") == "fr"
    assert normalize_language("zh-CN") == "zh"
    assert normalize_language("de") == "fr"


# =============================================================================
# current_language — fallback outside a user context
# =============================================================================

@pytest.mark.asyncio
async def test_current_language_defaults_without_user(monkeypatch):
    async def _no_user():
        return None

    monkeypatch.setattr("core.user.user_service.get_current_user", _no_user)
    assert await i18n_service.current_language() == i18n_service.default_language()


@pytest.mark.asyncio
@pytest.mark.parametrize("user_language,fallback,expected", [
    ("fr", "en", "fr"),
    ("zh", "fr", "zh"),
    ("FR-fr", "en", "fr"),
    (None, "zh-CN", "zh"),
    (None, None, "en"),
])
async def test_current_language_prioritizes_user_over_context_and_empty_preferences(
    monkeypatch, user_language, fallback, expected,
):
    monkeypatch.setattr(runtime_settings, "DEFAULT_LANGUAGE", "")
    monkeypatch.setattr(
        "core.user.user_service.get_current_user",
        AsyncMock(return_value=SimpleNamespace(language=user_language) if user_language else None),
    )

    assert await i18n_service.current_language(fallback) == expected


def _flatten_messages(
    value: dict[str, Any],
    prefix: str = "",
) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, child in value.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            flattened.update(_flatten_messages(cast(dict[str, Any], child), dotted))
        else:
            assert isinstance(child, str), f"{dotted} must be a string"
            assert child.strip(), f"{dotted} must not be empty"
            flattened[dotted] = child
    return flattened


def _message_placeholders(value: str) -> set[str]:
    return set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value))


def test_module_catalogs_have_complete_language_pairs() -> None:
    assert SUPPORTED_LANGUAGES == ("en", "fr", "zh")
    checked_pairs = 0

    for package_name in catalog._discover_packages():
        package = importlib.import_module(package_name)
        messages = cast(dict[str, dict[str, Any]], package.messages)
        assert {"en", "fr"}.issubset(messages), package_name

        english = _flatten_messages(messages["en"])
        french = _flatten_messages(messages["fr"])
        assert english.keys() == french.keys(), package_name

        for key in english:
            assert _message_placeholders(english[key]) == _message_placeholders(french[key]), (
                f"{package_name}.{key} uses different placeholders in English and French"
            )
        if "zh" in messages:
            chinese = _flatten_messages(messages["zh"])
            assert english.keys() == chinese.keys(), package_name
            for key in english:
                assert _message_placeholders(english[key]) == _message_placeholders(chinese[key]), (
                    f"{package_name}.{key} uses different placeholders in English and Chinese"
                )
        checked_pairs += len(english)

    assert checked_pairs > 0


def test_aggregate_catalog_loads_lab_without_importing_domain_package() -> None:
    """Pure catalog loading must not trigger the lab/task model import cycle."""
    catalog.get_messages.cache_clear()

    messages = catalog.get_messages()

    assert messages["en"]["evaluation_api"]["errors"]["suite_not_found"] == (
        "Suite not found"
    )
    assert messages["fr"]["evaluation_api"]["errors"]["suite_not_found"] == (
        "Suite introuvable"
    )
    assert messages["zh"]["user_api"]["errors"]["user_not_found"] == "未找到用户"
