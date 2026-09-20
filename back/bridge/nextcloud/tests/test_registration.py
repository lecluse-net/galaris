from types import SimpleNamespace

import bridge.nextcloud

from app.file_share import available_bridges
from app.messenger import get_spec, kind_for_tool


def test_nextcloud_registers_messaging_and_file_share_facades() -> None:
    assert kind_for_tool(
        SimpleNamespace(
            code="combined-nextcloud",
            messenger=SimpleNamespace(service="nextcloud_talk"),
        )
    ) == "nextcloud_talk"
    assert kind_for_tool(
        SimpleNamespace(code="nextcloud_talk", messenger=None)
    ) is None
    file_bridge = next(
        bridge for bridge in available_bridges() if bridge.service == "nextcloud"
    )
    assert {param.key for param in file_bridge.params} == {"login", "password"}
    messenger_spec = get_spec("nextcloud_talk")
    assert messenger_spec is not None
    assert {param.name for param in messenger_spec.connection_params} == {
        "login",
        "password",
    }
