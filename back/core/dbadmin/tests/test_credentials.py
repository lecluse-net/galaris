from urllib.parse import quote, quote_plus

import pytest

from core.dbadmin._internal import atlas


@pytest.mark.parametrize("secret", ["audit@reserved:slash/value", "spaces and+symbols%", "simple-password"])
@pytest.mark.parametrize("scrubber", [atlas._scrub, atlas._bounded_plan])
def test_atlas_credentials_are_redacted_without_losing_diagnostics(monkeypatch, secret, scrubber):
    monkeypatch.setattr(atlas.settings, "POSTGRES_PASSWORD", secret)
    message = f"cannot add column: {atlas._atlas_database_url('public')} {secret} {quote(secret, safe='')} {quote_plus(secret)}"
    redacted = scrubber(message)
    for variant in {secret, quote(secret, safe=""), quote_plus(secret)}:
        assert variant not in redacted
    assert "cannot add column" in redacted
    assert "search_path=public" in redacted
