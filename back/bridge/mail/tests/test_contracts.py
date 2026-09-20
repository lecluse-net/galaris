import pytest

from bridge.mail.contracts import MailMessageRef
from bridge.mail.service import parse_attachment_locator


def test_message_reference_round_trip_is_opaque_and_mailbox_safe() -> None:
    reference = MailMessageRef(mailbox="Boîte/Envoyés", uid_validity=42, uid=9)

    encoded = reference.encode()

    assert encoded.startswith("m1_")
    assert MailMessageRef.decode(encoded) == reference


@pytest.mark.parametrize("value", ["", "m2_x", "m1_%%%", "../../INBOX"])
def test_invalid_message_reference_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        MailMessageRef.decode(value)


def test_attachment_locator_keeps_filename_cosmetic() -> None:
    reference = MailMessageRef(mailbox="INBOX", uid_validity=1, uid=2).encode()

    message_ref, part_id, filename = parse_attachment_locator(
        f"attachment/{reference}/part-3/report%202026.pdf"
    )

    assert message_ref == reference
    assert part_id == "part-3"
    assert filename == "report 2026.pdf"
