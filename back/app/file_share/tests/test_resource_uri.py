from uuid import uuid4

import pytest

from app.file_share.resource_uri import (
    ResourceUriError,
    parse_resource_uri,
    validate_external_tool_code,
)


def test_resource_uri_normalization_is_canonical_and_idempotent() -> None:
    normalized = parse_resource_uri("NextCloud://Shared//Équipe/./rapport final.pdf")

    assert str(normalized) == "nextcloud://Shared/%C3%89quipe/rapport%20final.pdf"
    assert parse_resource_uri(str(normalized)) == normalized


@pytest.mark.parametrize(
    "value",
    [
        "console://../secret",
        "console://safe/%2e%2e/secret",
        "console://safe/%00secret",
        "console://safe/file?token=secret",
    ],
)
def test_resource_uri_rejects_ambiguous_or_unsafe_locators(value: str) -> None:
    with pytest.raises(ResourceUriError):
        parse_resource_uri(value)


def test_relative_path_is_rejected_without_an_explicit_provider() -> None:
    with pytest.raises(ResourceUriError, match="explicit scheme"):
        parse_resource_uri("reports/result.pdf")


def test_retired_workspace_scheme_is_rejected_explicitly() -> None:
    with pytest.raises(ResourceUriError, match="has been removed"):
        parse_resource_uri("workspace://reports/result.pdf")


def test_web_uri_normalizes_unicode_spaces_and_idn() -> None:
    assert str(
        parse_resource_uri("https://ÉXAMPLE.test/Équipe/rapport final.pdf?q=été")
    ) == (
        "https://xn--xample-9ua.test/%C3%89quipe/rapport%20final.pdf?q=%C3%A9t%C3%A9"
    )


def test_memory_and_document_uris_accept_only_their_canonical_shapes() -> None:
    identifier = uuid4()
    attachment_id = uuid4()
    assert str(parse_resource_uri(f"document://{identifier}")) == (
        f"document://{identifier}"
    )
    assert str(parse_resource_uri(f"document://{identifier}/attachments")) == (
        f"document://{identifier}/attachments/"
    )
    assert str(
        parse_resource_uri(f"document://{identifier}/attachments/{attachment_id}")
    ) == f"document://{identifier}/attachments/{attachment_id}"
    with pytest.raises(ResourceUriError):
        parse_resource_uri("document://folder/report.md")
    with pytest.raises(ResourceUriError):
        parse_resource_uri(f"document://{identifier}/attachments/not-a-uuid")


@pytest.mark.parametrize(
    "code",
    ["http", "https", "ssh", "workspace", "messenger", "galaris", "image", "n8n", "task"],
)
def test_reserved_tool_codes_are_rejected(code: str) -> None:
    with pytest.raises(ValueError, match="reserved"):
        validate_external_tool_code(code, file_share=True)


def test_file_share_tool_code_must_be_a_uri_scheme() -> None:
    assert validate_external_tool_code("nextcloud-pro", file_share=True) == (
        "nextcloud-pro"
    )
    with pytest.raises(ValueError, match="lowercase URI scheme"):
        validate_external_tool_code("nextcloud_personal", file_share=True)


def test_messenger_tool_code_must_also_be_a_uri_scheme() -> None:
    assert validate_external_tool_code(
        "telegram-team",
        file_share=False,
        messenger=True,
    ) == "telegram-team"
    with pytest.raises(ValueError, match="lowercase URI scheme"):
        validate_external_tool_code(
            "telegram_team",
            file_share=False,
            messenger=True,
        )
