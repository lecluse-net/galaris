"""Reviewers see the frozen action, without transport internals or active markup."""

import pytest

from app.tools.authorization_presentation import notification_body, present_action


@pytest.mark.parametrize("language,title,to_label", [("fr", "Envoyer un e-mail", "Destinataires"),
                                                   ("en", "Send an email", "Recipients")])
def test_mail_review_uses_frozen_recipients_content_and_attachments(language, title, to_label):
    arguments = {"to": ["original@example.test"], "subject": "Original draft", "body": "Old text",
                 "idempotency_key": "synthetic-key", "prepared": {
                     "to": ["recipient@example.test"], "cc": ["copy@example.test"], "bcc": ["hidden@example.test"],
                     "subject": "Synthetic greeting", "body": "Hello,\n\nHave a good day.",
                     "attachments": [{"filename": "greeting.txt", "sha256": "synthetic-hash", "size": 42}],
                     "delivery_id": "synthetic-delivery", "mime_sha256": "synthetic-mime"}}
    presentation = present_action(name="mail_send", source="domain", arguments=arguments, language=language)
    assert presentation["title"] == title
    assert presentation["fields"][0] == {"label": to_label, "value": "recipient@example.test"}
    body = notification_body(presentation, language=language)
    for expected in ("copy@example.test", "hidden@example.test", "Synthetic greeting", "Have a good day.", "greeting.txt"):
        assert expected in body
    for technical in ("Original draft", "Old text", "original@example.test", "synthetic-key", "synthetic-delivery", "synthetic-mime", "synthetic-hash"):
        assert technical not in body
    assert arguments["subject"] == "Original draft"


def test_generic_review_retains_nested_parameters_false_and_zero_and_redacts_secrets():
    presentation = present_action(name="external_action", source="mcp", arguments={
        "custom_options": {"enabled": False, "limit": 0}, "token": "synthetic-secret",
        "url": "https://example.test/path?token=synthetic-url-secret", "empty": None,
    }, language="en")
    fields = {field["label"]: field["value"] for field in presentation["fields"]}
    assert fields["Custom options"] == "enabled: No\nlimit: 0"
    assert fields["Web address"] == "https://example.test/path"
    assert fields["Token"] == "[redacted]"
    assert "Empty" not in fields
    assert "synthetic-secret" not in str(presentation)


def test_markup_is_inert_and_shortened_notifications_are_explicit():
    presentation = present_action(name="external_action", source="mcp", arguments={
        "content": '<img src="https://example.test/track">\n[Approve](https://example.test)\n```html\n<script>alert(1)</script>\n```',
    }, language="en")
    body = notification_body(presentation, language="en")
    assert "<img" not in body and "<script" not in body and "[Approve](" not in body and "```" not in body
    presentation["fields"][0]["value"] = "x" * 7000
    assert "Shortened preview" in notification_body(presentation, language="en")
    assert len(presentation["fields"][0]["value"]) == 7000
