"""Provider-profile contracts and registry owned by the LLM domain.

External provider declarations live in ``bridge.*`` packages and register an
immutable profile here. Database rows in ``LLMProvider`` remain user-owned
connections to those profiles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .capabilities import AICapability


# Provider protocol identifiers are bridge-owned and intentionally open-ended.
ProviderType = str
ProviderAuthType = Literal["api_key", "oauth_device", "optional_api_key"]


@dataclass(frozen=True, slots=True)
class ProviderConfigurationField:
    """Public, non-secret configuration field required by one provider driver."""

    key: str
    label: str
    required: bool = False
    placeholder: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Immutable definition of one built-in provider connection."""

    code: str
    display_name: str
    provider_type: ProviderType
    auth_type: ProviderAuthType
    base_url: str
    token_url: Optional[str]
    documentation_url: str
    icon: str
    color: str
    models_dev_id: Optional[str] = None
    supports_transcription: bool = False
    supports_responses: bool = False
    aliases: tuple[str, ...] = ()
    capabilities: tuple[AICapability, ...] = ("chat",)
    configuration_fields: tuple[ProviderConfigurationField, ...] = ()

    @property
    def api_key_required(self) -> bool:
        """Whether activation normally requires a user-supplied API key."""
        return self.auth_type == "api_key"


PROVIDER_CATALOG: list[ProviderProfile] = []
_PROVIDERS_BY_CODE: dict[str, ProviderProfile] = {}


def register_provider_profile(profile: ProviderProfile) -> None:
    """Register or replace one provider declaration idempotently."""

    previous = _PROVIDERS_BY_CODE.get(profile.code)
    if previous == profile:
        return
    if previous is not None:
        PROVIDER_CATALOG.remove(previous)
    _PROVIDERS_BY_CODE[profile.code] = profile
    PROVIDER_CATALOG.append(profile)


def get_provider_profile(code: Optional[str]) -> Optional[ProviderProfile]:
    """Return a built-in profile by its stable code."""
    if not code:
        return None
    return _PROVIDERS_BY_CODE.get(code)


def _normalize_url(value: str) -> str:
    return value.strip().rstrip("/").lower()


def match_provider_profile(base_url: str) -> Optional[ProviderProfile]:
    """Match a legacy connection to a built-in profile by exact endpoint."""
    normalized = _normalize_url(base_url)
    if not normalized:
        return None
    for profile in PROVIDER_CATALOG:
        candidates = (profile.base_url, *profile.aliases)
        if normalized in {_normalize_url(candidate) for candidate in candidates}:
            return profile
    return None


def resolve_provider_profile(
    *,
    catalog_code: Optional[str],
    base_url: str,
) -> Optional[ProviderProfile]:
    """Resolve a configured connection, including pre-catalog legacy rows."""
    return get_provider_profile(catalog_code) or match_provider_profile(base_url)


__all__ = [
    "PROVIDER_CATALOG",
    "ProviderAuthType",
    "ProviderConfigurationField",
    "ProviderProfile",
    "ProviderType",
    "get_provider_profile",
    "match_provider_profile",
    "register_provider_profile",
    "resolve_provider_profile",
]
