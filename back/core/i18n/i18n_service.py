"""Backend internationalization service.

The current request language comes from ``User.language``. Background work, scheduled jobs,
and autonomous tasks fall back to ``runtime_settings.DEFAULT_LANGUAGE``.

Usage::

    >>> from core.i18n import tr, render_prompt
    >>> template = await tr("prompts.planner_notice")
    >>> prompt = render_prompt("Hello ${agent_name}", agent_name="Ada")
"""

import re
from loguru import logger
from typing import Any, Optional, TypeGuard, cast

from core.params.runtime_settings import runtime_settings
from .catalog import SUPPORTED_LANGUAGES, get_messages


def is_supported(lang: Optional[str]) -> TypeGuard[str]:
    return lang in SUPPORTED_LANGUAGES


def default_language() -> str:
    """Return the fallback language used outside a user context."""
    language = runtime_settings.DEFAULT_LANGUAGE
    return language if is_supported(language) else "en"


def normalize_language(value: object) -> str:
    """Normalize a persisted language code with the instance default as fallback."""

    normalized = str(value or "").strip().lower().split("-", 1)[0]
    return normalized if is_supported(normalized) else default_language()


async def current_language(fallback: object = None, *, user_id: int | None = None) -> str:
    """Prefer the current user, then the source language, instance setting, and English.

    Background admission can supply the durable requester as ``user_id``.
    ``core.user`` is imported lazily to avoid a startup import cycle.
    """
    try:
        from core.user import user_service

        user = (
            await user_service.get_user_by_id(user_id)
            if user_id is not None else await user_service.get_current_user()
        )
        if user is not None:
            language = str(user.language or "").strip().lower().split("-", 1)[0]
            if is_supported(language):
                return language
    except Exception as exc:
        logger.warning(
            "Unable to resolve the authenticated user's language: {}",
            type(exc).__name__,
        )
    return normalize_language(fallback)


def _lookup(messages: dict[str, Any], key: str) -> Optional[str]:
    """Resolve a dotted key such as ``prompts.planner_notice`` in a nested dictionary."""
    node: Any = messages
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = cast(dict[str, Any], node)[part]
    return node if isinstance(node, str) else None


def t(key: str, lang: Optional[str] = None) -> str:
    """Return a message for ``key`` with default-language and raw-key fallbacks.

    No substitution occurs here, so placeholders remain intact.
    """
    lang = lang if is_supported(lang) else default_language()
    messages = get_messages()
    value = _lookup(messages.get(lang, {}), key)
    if value is None and lang != default_language():
        value = _lookup(messages[default_language()], key)
    return value if value is not None else key


async def tr(key: str) -> str:
    """Resolve ``t`` in the current user's language."""
    return t(key, await current_language())


def render_prompt(
    template: str,
    *,
    optional_sections: Optional[dict[str, str]] = None,
    **values: Any,
) -> str:
    """Render ``${name}`` placeholders without interpreting other braces.

    ``optional_sections`` maps a value name to an XML tag. When that value is absent or empty,
    the complete tagged block is removed before substitution so prompts contain no empty section.
    """
    for value_name, tag in (optional_sections or {}).items():
        raw = values.get(value_name)
        if raw is None or not str(raw).strip():
            template = re.sub(
                rf"\n?<{re.escape(tag)}>.*?</{re.escape(tag)}>",
                "",
                template,
                flags=re.DOTALL,
            )

    normalized = {key: "" if value is None else str(value) for key, value in values.items()}
    return re.sub(
        r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
        lambda match: normalized.get(match.group(1), match.group(0)),
        template,
    ).strip()
