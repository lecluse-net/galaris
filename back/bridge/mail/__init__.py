"""IMAP/SMTP Mail bridge exposed as one built-in Tool."""

from app.messenger.facade import register_bridge
from app.messenger.interface import BridgeSpec

from .messenger import MailMessenger
from .models import MailOutboundDelivery, MailInboundReceipt
from . import inbound as inbound
from .file_transport import MailAttachmentTransport
from .approvals import retry_approval_notifications
from app.file_share.interface import register_resource_transport

SPEC = BridgeSpec(
    kind="mail",
    label="Mail",
    capabilities=set(MailMessenger.capabilities),
    inbound_modes=["polling"],
    availability="tool",
    inbound_admission="task",
    deliver_task_result=False,
)

register_bridge(SPEC.kind, MailMessenger, SPEC)
register_resource_transport("mail", MailAttachmentTransport)


async def _test_saved_connection(connection_id: int) -> bool:
    from .service import test_connection

    result = await test_connection(connection_id)
    return result.imap_ok and result.smtp_ok


from app.tools import register_connection_probe

register_connection_probe("mail", _test_saved_connection)

__all__ = ["MailMessenger", "MailOutboundDelivery", "MailInboundReceipt", "SPEC", "retry_approval_notifications"]
