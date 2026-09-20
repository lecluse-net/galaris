"""IMAP/SMTP Mail bridge exposed as one built-in Tool."""

from app.messenger.facade import register_bridge
from app.messenger.interface import BridgeSpec

from .messenger import MailMessenger
from .models import MailOutboundDelivery
from .file_transport import MailAttachmentTransport
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

__all__ = ["MailMessenger", "MailOutboundDelivery", "SPEC"]
