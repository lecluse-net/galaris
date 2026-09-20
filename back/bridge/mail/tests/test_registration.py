from app.tools.mandatory_tools import INTEGRATED_TOOL_SPECS, mandatory_tool_rows
from app.tools.mcp_loader import mcp_tool_names_by_tool_code
from bridge.mail import SPEC
from bridge.mail.assertions import MailApproverAssertion
from bridge.mail.router import (
    approve_outbound_mail,
    list_mail_approvers,
    read_mail_status,
    reject_outbound_mail,
)
from core.authorize import Privileges


EXPECTED_FUNCTIONS = {
    "mail_connection_status",
    "mail_list_mailboxes",
    "mail_search",
    "mail_get",
    "mail_send",
    "mail_reply",
    "mail_forward",
    "mail_set_flags",
    "mail_move",
    "mail_trash",
}


def test_mail_tool_is_explicit_and_discovers_all_mcp_functions() -> None:
    spec = next(item for item in INTEGRATED_TOOL_SPECS if item.code == "mail")

    assert spec.auto_connect_agents is False
    assert spec.default_active is False
    assert spec.file_share_service == "mail"
    assert spec.messenger_service == "mail"
    assert set(mcp_tool_names_by_tool_code()["mail"]) == EXPECTED_FUNCTIONS
    assert SPEC.inbound_modes == ["polling"]
    assert SPEC.availability == "tool"
    assert SPEC.inbound_admission == "task"
    assert SPEC.deliver_task_result is False


def test_mail_connection_schema_uses_one_account_password_and_safe_defaults() -> None:
    row = next(item for item in mandatory_tool_rows() if item["code"] == "mail")
    params = row["connection_schema"]["params"]

    assert params["password"]["type"] == "password"
    assert "imap_username" not in params
    assert "smtp_username" not in params
    assert params["imap_security"]["default"] == "tls"
    assert params["smtp_security"]["default"] == "tls"
    assert params["poll_interval_s"]["default"] == "60"
    assert params["max_attachment_mb"]["default"] == "10"
    assert params["max_total_attachment_mb"]["default"] == "20"
    assert params["approval_required"]["type"] == "boolean"
    assert params["approval_required"]["required"] is False
    assert params["approval_required"]["default"] == "false"
    assert params["approver_user_id"]["type"] == "user"
    assert params["approver_user_id"]["required"] is False
    assert "max_attachment_bytes" not in params
    assert "max_total_attachment_bytes" not in params
    assert row["file_share_config"]["service"] == "mail"
    assert row["messenger_config"] == {
        "service": "mail",
        "settings": {},
        "param_map": {},
    }


def test_approver_directory_is_available_to_connection_readers() -> None:
    metadata = getattr(list_mail_approvers, "_authorize_meta")

    assert metadata["privileges"] == [
        Privileges.CONNECTION_ACCESS,
        Privileges.TOOL_EDIT,
        Privileges.CONNECTION_EDIT,
    ]


def test_outbound_reviews_require_the_official_approver_assertion() -> None:
    for endpoint in (approve_outbound_mail, reject_outbound_mail):
        metadata = getattr(endpoint, "_authorize_meta")
        assert metadata["privileges"] == [Privileges.CONNECTION_ACCESS]
        assert metadata["assertion"] is MailApproverAssertion


def test_mail_availability_requires_connection_access() -> None:
    metadata = getattr(read_mail_status, "_authorize_meta")

    assert metadata["privileges"] == [Privileges.CONNECTION_ACCESS]
