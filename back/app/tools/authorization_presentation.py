"""Human-readable projections of an approval's immutable, redacted arguments."""

import re
from html import escape
from typing import TypedDict, cast

from core.i18n import render_prompt, t

from .authorization import redacted_action_arguments


class ApprovalField(TypedDict):
    label: str
    value: str


class ApprovalPresentation(TypedDict):
    title: str
    fields: list[ApprovalField]


def _value(value: object, language: str) -> str:
    if isinstance(value, dict):
        return "\n".join(f"{str(key).replace('_', ' ')}: {_value(item, language)}"
                         for key, item in cast(dict[str, object], value).items())
    if isinstance(value, list):
        return "\n".join(_value(item, language) for item in cast(list[object], value))
    if isinstance(value, bool):
        return t("approval_preview.yes" if value else "approval_preview.no", language)
    return str(value) if value is not None else "—"


def present_action(*, name: str, source: str, arguments: dict[str, object], language: str) -> ApprovalPresentation:
    arguments = cast(dict[str, object], redacted_action_arguments(arguments))
    fields: list[ApprovalField] = []
    mail = source == "domain" and name in {"mail_send", "mail_reply", "mail_forward"}
    title = t("approval_preview.send_mail", language) if mail else render_prompt(
        t("approval_preview.run_function", language), function=name)
    if mail and isinstance(arguments.get("prepared"), dict):
        # The frozen delivery is what will be sent, even when original inputs differ.
        snapshot = cast(dict[str, object], arguments["prepared"])
        values = {key: snapshot.get(key) for key in ("to", "cc", "bcc", "subject", "body", "html_body", "attachments")}
        values["reply_to"] = arguments.get("reply_to")
    else:
        values = arguments
    for key, value in values.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        label_key = key if key in {"to", "cc", "bcc", "subject", "body", "html_body", "reply_to", "attachments",
                                   "command", "cwd", "path", "url", "content", "destination", "source"} else None
        label = t(f"approval_preview.{label_key}", language) if label_key else key.replace("_", " ").capitalize()
        if mail and key == "attachments" and isinstance(value, list):
            value = [cast(dict[str, object], item).get("filename", cast(dict[str, object], item)) if isinstance(item, dict) else item
                     for item in cast(list[object], value)]
        fields.append({"label": label, "value": _value(value, language)})
    return {"title": title, "fields": fields}


def notification_body(presentation: ApprovalPresentation, *, language: str) -> str:
    def escaped(value: str) -> str:
        # Mail and tool content stays inert in Markdown/HTML-aware messengers.
        return re.sub(r"([\\`*_\[\]#|~])", r"\\\1", escape(value, quote=False))

    body = escaped(presentation["title"]) + "\n\n" + "\n\n".join(
        f"{escaped(field['label'])} :\n{escaped(field['value'])}" for field in presentation["fields"])
    if len(body) > 6000:
        body = body[:6000] + "\n\n" + t("approval_preview.truncated", language)
    return body
