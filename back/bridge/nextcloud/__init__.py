"""Unified Nextcloud bridge for Talk messaging, calls, and file sharing."""

from app.file_share import register as register_file_share_bridge
from app.messenger.facade import register_bridge
from app.messenger.interface import BridgeSpec, ParamDef
from app.voice.facade import register_call_provider

from .file_share import NEXTCLOUD_FILE_SHARE_BRIDGE, NextcloudFileClient
from .messenger import NextcloudTalkMessenger
from .voice_provider import NEXTCLOUD_TALK_VOICE_PROVIDER


SPEC = BridgeSpec(
    kind="nextcloud_talk",
    label="Nextcloud Talk",
    identity_param="login",
    tool_params=[
        ParamDef(
            "base_url",
            description="Nextcloud server URL shared by the Tool",
        ),
    ],
    connection_params=[
        ParamDef("login", description="Nextcloud login for the agent account"),
        ParamDef("password", type="password", description="Nextcloud password"),
    ],
    capabilities=set(NextcloudTalkMessenger.capabilities),
    inbound_modes=["polling", "signaling"],
)

register_bridge(SPEC.kind, NextcloudTalkMessenger, SPEC)
register_file_share_bridge(NEXTCLOUD_FILE_SHARE_BRIDGE)
register_call_provider(NEXTCLOUD_TALK_VOICE_PROVIDER)

__all__ = [
    "NEXTCLOUD_FILE_SHARE_BRIDGE",
    "NEXTCLOUD_TALK_VOICE_PROVIDER",
    "NextcloudFileClient",
    "NextcloudTalkMessenger",
    "SPEC",
]
