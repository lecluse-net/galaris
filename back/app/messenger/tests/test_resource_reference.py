from uuid import uuid4

import pytest

from app.messenger.resource_reference import attachment_resource_uri


def test_attachment_resource_uri_uses_exact_tool_code_and_provider_room() -> None:
    file_id = uuid4()

    assert attachment_resource_uri("chat", "chat:direct:1:7", file_id) == (
        f"chat://chat:direct:1:7/{file_id}"
    )
    assert attachment_resource_uri("nextcloud", "talk token", file_id) == (
        f"nextcloud://talk%20token/{file_id}"
    )
    assert attachment_resource_uri("telegram", "-10042", file_id) == (
        f"telegram://-10042/{file_id}"
    )


@pytest.mark.parametrize("tool_code", ["", "Messenger", "messenger", "workspace"])
def test_attachment_resource_uri_rejects_capability_or_native_schemes(
    tool_code: str,
) -> None:
    with pytest.raises(ValueError, match="Tool code"):
        attachment_resource_uri(tool_code, "room", uuid4())
