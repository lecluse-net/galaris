from __future__ import annotations

import pytest

from app.messenger import facade
from core.params.runtime_settings import runtime_settings


def test_enabled_registry_is_a_validated_runtime_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert {"matrix", "telegram", "whatsapp"} <= set(facade.registered_kinds())
    monkeypatch.setattr(
        runtime_settings,
        "MESSENGER_ENABLED_CHANNELS",
        '["matrix","telegram"]',
    )

    assert facade.enabled_kinds() == [
        kind
        for kind in facade.registered_kinds()
        if kind in {"matrix", "telegram"}
    ]
    assert facade.is_kind_enabled("matrix") is True
    assert facade.is_kind_enabled("whatsapp") is False
