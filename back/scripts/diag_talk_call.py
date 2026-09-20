"""Diagnose why a Nextcloud Talk HPB audio call returns ``no_such_room``.

In read-only mode, rebuild the connection's ``NextcloudTalkClient`` through the same
path as ``TalkCall.from_connection_id`` and dump the raw Talk API responses hidden
by normal logs: room call permissions, ``canStartCall``, ``signalingMode``,
participant permissions and sessions, and the complete ``POST /call`` error body.

Usage (inside the backend container with the production environment loaded):

    docker exec galaris-back python scripts/diag_talk_call.py <connection_id> <room_token>
    # example: docker exec galaris-back python scripts/diag_talk_call.py 11 cczezx7q

The default is read-only. Add ``--write`` to execute the POST requests
(``participants/active`` and ``call``) that reproduce the failure and dump the 404 body.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from typing import Any, Awaitable

from core.database import get_db_session
from core.util import as_dict, as_list

_SENSITIVE_KEY_PARTS = (
    "credential",
    "password",
    "requesttoken",
    "resumeid",
    "secret",
    "ticket",
    "token",
)
_SESSION_KEY_PARTS = (
    "nextcloudsessionid",
    "sessionid",
    "sessionids",
)


def _fingerprint(value: Any) -> dict[str, Any]:
    text = str(value or "")
    if not text:
        return {"empty": True}
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "len": len(text),
        "sha256": digest[:16],
        "prefix": text[:10],
        "suffix": text[-10:],
    }


def _redact(value: Any, *, key: str = "") -> Any:
    key_lower = key.lower()
    if isinstance(value, dict):
        return {str(k): _redact(v, key=str(k)) for k, v in as_dict(value).items()}
    if isinstance(value, list):
        if any(part in key_lower for part in _SESSION_KEY_PARTS):
            return [_fingerprint(item) for item in as_list(value)]
        return [_redact(item, key=key) for item in as_list(value)]
    if any(part in key_lower for part in _SESSION_KEY_PARTS):
        return _fingerprint(value)
    if any(part in key_lower for part in _SENSITIVE_KEY_PARTS) and isinstance(
        value, (str, bytes, bytearray)
    ):
        return {"redacted": True, **_fingerprint(value)}
    return value


def _dump(label: str, value: Any) -> None:
    print(f"\n===== {label} =====")
    try:
        print(json.dumps(_redact(value), indent=2, ensure_ascii=False, default=str))
    except Exception:
        print(repr(value))


async def _build_client(connection_id: int):
    from core.database.model_loader import load_models
    load_models()  # Register every SQLAlchemy mapper and cross-module relationship.

    from bridge.nextcloud.client import NextcloudTalkClient
    from bridge.nextcloud.credentials import resolve_nextcloud_connection

    config = await resolve_nextcloud_connection(connection_id)
    print(
        "connection={} host={} login={} self_id={} authenticated={}".format(
            connection_id,
            config.base_url,
            config.login,
            config.self_id,
            bool(config.password),
        )
    )
    client = NextcloudTalkClient(
        base_url=config.base_url,
        login=config.login,
        password=config.password,
    )
    return client, config.self_id


async def _safe(label: str, coro: Awaitable[Any]) -> Any:
    try:
        res = await coro
        _dump(label, res)
        return res
    except Exception as exc:  # noqa: BLE001 - diagnostic command
        body = ""
        resp = getattr(exc, "response", None)
        if resp is not None:
            body = getattr(resp, "text", "")
        _dump(f"{label} - ERROR", {"type": type(exc).__name__, "error": str(exc), "body": body})
        return None


async def _probe_hpb_room_join(
    client: Any,
    token: str,
    self_id: str,
    session: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    import websockets
    from bridge.nextcloud.signaling import (
        _SUBPROTOCOL,  # pyright: ignore[reportPrivateUsage]
        build_hello_message,
        build_room_join_message,
        extract_hpb_url,
    )

    session_id = str(session.get("sessionId") or "")
    if not session_id:
        return {"ok": False, "error": "sessionId is empty"}

    hpb_url = extract_hpb_url(settings)
    if not hpb_url:
        return {"ok": False, "error": "HPB not found in signaling/settings"}

    result: dict[str, Any] = {
        "hpb_url": hpb_url,
        "nextcloud_url": client.base_url,
        "sessionId": session_id,
    }

    async with websockets.connect(hpb_url, subprotocols=[_SUBPROTOCOL]) as ws:  # type: ignore[arg-type]
        hello = build_hello_message(
            client.base_url,
            settings,
            legacy_room_token=token,
            legacy_session_id=session_id,
            legacy_user_id=self_id,
        )
        await ws.send(json.dumps(hello))
        result["hello_sent"] = hello
        hello_resp = await _recv_hpb_until(ws, "hello", timeout=10.0)
        result["hello_response"] = hello_resp

        room_join = build_room_join_message(token, session_id, settings)
        await ws.send(json.dumps(room_join))
        result["room_sent"] = room_join
        room_resp = await _recv_hpb_until(ws, "room", timeout=10.0, allow_error=True)
        result["room_response"] = room_resp
        result["ok"] = room_resp.get("type") == "room"
        return result


async def _recv_hpb_until(
    ws: Any,
    expected_type: str,
    *,
    timeout: float,
    allow_error: bool = False,
) -> dict[str, Any]:
    async def _loop() -> dict[str, Any]:
        seen: list[dict[str, Any]] = []
        while True:
            raw = await ws.recv()
            try:
                event = json.loads(raw)
            except Exception:
                continue
            if isinstance(event, dict):
                ev = as_dict(event)
                current_type = ev.get("type")
                if current_type == expected_type:
                    if seen:
                        ev["_seen_before"] = seen
                    return ev
                if current_type == "error":
                    if allow_error:
                        if seen:
                            ev["_seen_before"] = seen
                        return ev
                    raise RuntimeError(f"HPB error: {ev.get('error') or ev}")
                if current_type not in {"welcome", "pong"}:
                    seen.append(ev)

    return await asyncio.wait_for(_loop(), timeout=timeout)


async def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: diag_talk_call.py <connection_id> <room_token>")
    connection_id = int(sys.argv[1])
    token = sys.argv[2]
    do_writes = "--write" in sys.argv[3:]
    print(f"mode={'WRITE (POST enabled)' if do_writes else 'READ ONLY'}")

    async with get_db_session():
        from core.params import params_service

        await params_service.load_params()
        client, self_id = await _build_client(connection_id)
        v4 = "/ocs/v2.php/apps/spreed/api/v4"
        v1 = "/ocs/v2.php/apps/spreed/api/v1"
        try:
            # 1. Signaling settings: signalingMode (internal/external) and HPB server.
            settings = await _safe("signaling/settings", client.get_signaling_settings(token))
            if isinstance(settings, dict):
                s = as_dict(settings)
                _dump("signaling/settings (summary)", {
                    "signalingMode": s.get("signalingMode"),
                    "server": s.get("server"),
                    "helloAuthParams_keys": sorted(as_dict(s.get("helloAuthParams")).keys()),
                    "stunservers": len(as_list(s.get("stunservers"))),
                    "turnservers": len(as_list(s.get("turnservers"))),
                })

            # 2. Complete room object: permissions, callPermissions, canStartCall, lobby, and SIP.
            await _safe("GET room (complete)", client._request("GET", f"{v4}/room/{token}"))  # pyright: ignore[reportPrivateUsage]

            # 3. Complete participant data: permissions, sessions, and inCall state.
            await _safe("GET participants (complete)", client._request("GET", f"{v4}/room/{token}/participants"))  # pyright: ignore[reportPrivateUsage]

            if not do_writes:
                print("\n(read-only mode: participants/active and call POST requests skipped; use --write to include them)")
                return

            # 4. participants/active creates the session that the HPB validates next.
            session = await _safe("POST participants/active (runtime path)", client.join_call(token))

            # 5. Read participants again and check whether the session appeared.
            await _safe("GET participants (after active)", client._request("GET", f"{v4}/room/{token}/participants"))  # pyright: ignore[reportPrivateUsage]

            if isinstance(session, dict) and isinstance(settings, dict):
                await _safe(
                    "HPB probe hello + room join",
                    _probe_hpb_room_join(client, token, self_id, as_dict(session), as_dict(settings)),
                )

            # 6. POST /call through the runtime path, then use the raw v1 fallback if needed.
            await _safe("POST call (runtime path)", client.join_media_call(token, flags=3, silent=True))
            await _safe("GET call participants (runtime path)", client.get_call_participants(token))
            await _safe("POST call (raw v1)", client._request("POST", f"{v1}/call/{token}", json={"flags": 3, "silent": True}))  # pyright: ignore[reportPrivateUsage]
        finally:
            if do_writes:
                await _safe("DELETE call cleanup", client.leave_media_call(token))
            await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
