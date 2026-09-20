"""
Matrix messaging backend (Galaris <-> Matrix homeserver, using ``/sync``).

It registers with the ``app.messenger`` facade at import time and is listed in
``back/modules.py``. ``app.messenger.start_listeners`` starts its inbound long poll.
"""

from app.messenger.facade import register_bridge
from app.messenger.interface import BridgeSpec, ParamDef

from .messenger import MatrixMessenger, matrix_to_message

# Connection parameters identify the bot; homeserver and sync timeout come from
# database-backed application parameters.
SPEC = BridgeSpec(
    kind="matrix",
    label="Matrix",
    tool_params=[
        ParamDef(
            "homeserver",
            description="Matrix homeserver URL shared by the Tool",
        ),
    ],
    connection_params=[
        ParamDef("user_id", description="Matrix bot ID (for example @bot:example.org)"),
        ParamDef("token", type="password", required=False, description="Long-lived access token"),
        ParamDef("password", type="password", required=False, description="Password used when no token is provided"),
    ],
    capabilities=set(MatrixMessenger.capabilities),
    inbound_modes=["sync"],
)

register_bridge(SPEC.kind, MatrixMessenger, SPEC)
from app.voice.facade import register_call_provider

from .voice_provider import MATRIX_VOICE_PROVIDER

register_call_provider(MATRIX_VOICE_PROVIDER)

__all__ = ["MatrixMessenger", "matrix_to_message", "SPEC"]
