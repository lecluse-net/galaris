"""
OneBot v11 reverse-WebSocket messaging backend.

It registers with ``app.messenger`` at import time and is listed in
``back/modules.py``. Unlike Nextcloud Talk and Matrix, adapters such as Napcat
and Lagrange connect to Galaris and push events through ``onebot_router``.
"""

from app.messenger.facade import register_bridge
from app.messenger.interface import BridgeSpec, ParamDef

from .client import OneBot, OneBotMessage, MessageSender, MessengerHub, hub
from .messenger import OneBotMessenger, onebot_to_message
from .router import onebot_router

# Connection parameters identify each agent's bot; inbound events use push mode.
SPEC = BridgeSpec(
    kind="one_bot",
    label="OneBot 11",
    tool_params=[
        ParamDef(
            "platform",
            description="OneBot adapter platform shared by the Tool",
        ),
    ],
    connection_params=[
        ParamDef("user_id", description="Bot identifier on the OneBot platform"),
        ParamDef("token", type="password", description="OneBot reverse WebSocket token"),
    ],
    capabilities=set(OneBotMessenger.capabilities),
    inbound_modes=["push"],
)

register_bridge(SPEC.kind, OneBotMessenger, SPEC)
__all__ = [
    "OneBot",
    "OneBotMessage",
    "MessageSender",
    "MessengerHub",
    "hub",
    "OneBotMessenger",
    "onebot_to_message",
    "onebot_router",
    "SPEC",
]
