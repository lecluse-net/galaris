"""Official WhatsApp Business Cloud messaging bridge."""

from app.messenger.facade import register_bridge
from app.messenger.interface import BridgeSpec, ParamDef

from .messenger import WhatsAppMessenger, whatsapp_to_message

SPEC = BridgeSpec(
    kind="whatsapp",
    label="WhatsApp Cloud",
    tool_params=[
        ParamDef(
            "app_secret",
            type="password",
            description="Meta application secret used to verify webhook signatures",
        ),
        ParamDef(
            "verify_token",
            type="password",
            description="Token configured when registering the Meta webhook",
        ),
    ],
    connection_params=[
        ParamDef("access_token", type="password", description="Meta permanent access token"),
        ParamDef("phone_number_id", description="WhatsApp Business phone number ID"),
    ],
    capabilities=set(WhatsAppMessenger.capabilities),
    inbound_modes=["push"],
)

register_bridge(SPEC.kind, WhatsAppMessenger, SPEC)
__all__ = ["SPEC", "WhatsAppMessenger", "whatsapp_to_message"]
