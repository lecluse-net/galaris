"""English voice-call messages exposed to agents."""

default: dict[str, object] = {
    "voice": {
        "initial_greeting": "Hello?",
        "disabled": "Audio mode is disabled on this server (VOICE_ENABLED=false).",
        "room_required": "Could not start the call: room_id is required.",
        "agent_missing": "Could not start the call: agent not found.",
        "already_active": (
            "A voice call is already active for this room. call_id=${call_id}, room_id=${room_id}."
        ),
        "started": (
            "Voice call started in the background. call_id=${call_id}, room_id=${room_id}."
        ),
        "start_failed": "Voice call start failed: ${error}",
        "stopped": "Voice call stopped.",
        "call_missing": "No active call has this call_id.",
        "none_to_stop": "There is no active voice call to stop.",
        "stopped_count": "${count} voice call(s) stopped.",
        "stop_failed": "Voice call stop failed: ${error}",
        "none_active": "There are no active voice calls.",
        "call_line": (
            "- call_id=${call_id} room_id=${room_id} transport=${transport_kind}"
        ),
        "provider_missing": "No voice-call provider is registered for ${provider}.",
        "no_conversation_start": "No active conversation; a voice call cannot be started.",
        "no_conversation_stop": "No active conversation; a voice call cannot be stopped.",
        "no_conversation": "No active conversation.",
        "conversation_not_found": "Voice conversation not found.",
        "connection_not_found": "Connection ${connection_id} not found",
        "connection_wrong_agent": "Connection ${connection_id} does not belong to this agent",
        "connection_inactive": "Connection ${connection_id} is inactive",
        "connection_not_talk": "Connection ${connection_id} is not a Nextcloud Talk connection",
        "room_connection_missing": "No active Nextcloud Talk connection for agent ${agent_id} can see room ${room_id}",
        "talk_connection_missing": "No active Nextcloud Talk connection exists for this agent",
        "manager_room_required": "room_id is required",
        "manager_room_too_long": "room_id must not exceed 512 characters",
        "pulse_playback_unavailable": "pacat did not expose stdin.",
        "pulse_capture_unavailable": "parec did not expose stdout.",
        "pulse_capture_stopped": "parec stopped (${status}): ${error}",
    },
}
