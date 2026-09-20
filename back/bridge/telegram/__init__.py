"""Official Telegram Bot API messaging bridge."""

from app.messenger.facade import register_bridge
from app.messenger.interface import BridgeSpec, ParamDef

from .messenger import TelegramMessenger, telegram_to_message

SPEC = BridgeSpec(
    kind="telegram",
    label="Telegram",
    connection_params=[
        ParamDef("token", type="password", description="Telegram BotFather token"),
    ],
    capabilities=set(TelegramMessenger.capabilities),
    inbound_modes=["polling"],
)

register_bridge(SPEC.kind, TelegramMessenger, SPEC)
__all__ = ["SPEC", "TelegramMessenger", "telegram_to_message"]
