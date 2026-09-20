import asyncio

import httpx
import pytest

from bridge.nextcloud.client import NextcloudTalkClient
from app.messenger.interface import DeliveryOutcomeUnknown


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_5xx_is_uncertain_not_a_receipt_or_a_reason_to_resend(accepted):
    requests, effects = [], []
    def handler(request):
        requests.append(request)
        if accepted:
            effects.append(request.content)
        return httpx.Response(500)
    client = NextcloudTalkClient("https://cloud.test", "bot", "secret")
    client._client = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(DeliveryOutcomeUnknown):
            await client.send_message("room", "one message")
    finally:
        await client.aclose()
    assert len(requests) == 1
    assert len(effects) == int(accepted)


def _not_found(method: str, endpoint: str) -> httpx.HTTPStatusError:
    request = httpx.Request(method, f"https://cloud.test{endpoint}")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("not found", request=request, response=response)


@pytest.mark.asyncio
async def test_chat_page_preserves_server_cursor_and_caps_provider_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["lookIntoFuture"] == "0"
        assert request.url.params["limit"] == "200"
        assert request.url.params["lastKnownMessageId"] == "900"
        return httpx.Response(
            200,
            headers={"X-Chat-Last-Given": "700"},
            json={
                "ocs": {
                    "data": [
                        {
                            "id": 899,
                            "actorId": "alice",
                            "message": "hello",
                        }
                    ]
                }
            },
        )

    client = NextcloudTalkClient("https://cloud.test", "bot", "secret")
    client._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        base_url=client.base_url,
        transport=httpx.MockTransport(handler),
    )
    try:
        messages, cursor = await client.get_messages_page(
            "room-token",
            limit=500,
            last_known_message_id=900,
        )
    finally:
        await client.aclose()

    assert [message["id"] for message in messages] == [899]
    assert cursor == "700"


@pytest.mark.asyncio
async def test_web_login_sends_nextcloud_34_same_origin_headers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                text='<head data-requesttoken="csrf-token&#x3A;value">',
            )
        return httpx.Response(
            303,
            headers={"location": "/apps/dashboard/"},
        )

    client = NextcloudTalkClient(
        "https://cloud.test/nextcloud",
        "bot",
        "secret",
    )
    client._web_client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        base_url=client.base_url,
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    try:
        assert await client._ensure_web_session() is True  # pyright: ignore[reportPrivateUsage]
        assert await client._ensure_web_session() is True  # pyright: ignore[reportPrivateUsage]
    finally:
        await client.aclose()

    assert len(requests) == 2
    assert requests[1].headers["origin"] == "https://cloud.test"
    assert requests[1].headers["referer"] == "https://cloud.test/nextcloud/login"
    assert "requesttoken=csrf-token%3Avalue" in requests[1].content.decode()
    assert "password=secret" in requests[1].content.decode()


@pytest.mark.asyncio
async def test_concurrent_web_login_waits_for_shared_session() -> None:
    requests: list[httpx.Request] = []
    login_started = asyncio.Event()
    release_login = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            login_started.set()
            await release_login.wait()
            return httpx.Response(
                200,
                text='<head data-requesttoken="csrf-token">',
            )
        return httpx.Response(303, headers={"location": "/apps/dashboard/"})

    client = NextcloudTalkClient(
        "https://cloud.test",
        "bot",
        "secret",
    )
    client._web_client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        base_url=client.base_url,
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    try:
        first = asyncio.create_task(
            client._ensure_web_session()  # pyright: ignore[reportPrivateUsage]
        )
        await login_started.wait()
        followers = [
            asyncio.create_task(
                client._ensure_web_session()  # pyright: ignore[reportPrivateUsage]
            )
            for _ in range(4)
        ]
        await asyncio.sleep(0)
        release_login.set()
        assert await asyncio.gather(first, *followers) == [True] * 5
    finally:
        await client.aclose()

    assert len(requests) == 2


@pytest.mark.asyncio
async def test_call_api_falls_back_when_v4_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NextcloudTalkClient("https://cloud.test", "bot", "secret")
    calls: list[tuple[str, str]] = []

    async def unavailable_web_request(*_: object, **__: object) -> None:
        raise RuntimeError("unavailable")

    async def fake_request(method: str, endpoint: str, **_: object) -> dict[str, bool]:
        calls.append((method, endpoint))
        if "/api/v4/call/" in endpoint:
            raise _not_found(method, endpoint)
        return {"ok": True}

    monkeypatch.setattr(client, "_web_request", unavailable_web_request)
    monkeypatch.setattr(client, "_request", fake_request)

    assert await client.join_media_call("room-token", flags=3, silent=False) == {"ok": True}
    assert calls == [
        ("POST", "/ocs/v2.php/apps/spreed/api/v4/call/room-token"),
        ("POST", "/ocs/v2.php/apps/spreed/api/v3/call/room-token"),
    ]


@pytest.mark.asyncio
async def test_call_api_fallback_preserves_ring_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NextcloudTalkClient("https://cloud.test", "bot", "secret")
    calls: list[tuple[str, str]] = []

    async def unavailable_web_request(*_: object, **__: object) -> None:
        raise RuntimeError("unavailable")

    async def fake_request(method: str, endpoint: str, **_: object) -> dict[str, bool]:
        calls.append((method, endpoint))
        if "/api/v1/call/" not in endpoint:
            raise _not_found(method, endpoint)
        return {"ok": True}

    monkeypatch.setattr(client, "_web_request", unavailable_web_request)
    monkeypatch.setattr(client, "_request", fake_request)

    assert await client.ring_call_participant("room-token", 354) == {"ok": True}
    assert calls == [
        ("POST", "/ocs/v2.php/apps/spreed/api/v4/call/room-token/ring/354"),
        ("POST", "/ocs/v2.php/apps/spreed/api/v3/call/room-token/ring/354"),
        ("POST", "/ocs/v2.php/apps/spreed/api/v1/call/room-token/ring/354"),
    ]


@pytest.mark.asyncio
async def test_call_api_prefers_web_session(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NextcloudTalkClient(
        "https://cloud.test",
        "bot",
        "app-password",
    )
    calls: list[tuple[str, str, object]] = []

    async def fake_web_request(method: str, endpoint: str, **kwargs: object) -> dict[str, bool]:
        calls.append((method, endpoint, kwargs.get("data")))
        return {"ok": True}

    async def fake_basic_request(method: str, endpoint: str, **_: object) -> dict[str, bool]:
        raise AssertionError("Call API should prefer web session over Basic Auth")

    monkeypatch.setattr(client, "_web_request", fake_web_request)
    monkeypatch.setattr(client, "_request", fake_basic_request)

    assert await client.join_media_call("room-token", flags=3, silent=False) == {"ok": True}
    assert calls == [
        (
            "POST",
            "/ocs/v2.php/apps/spreed/api/v4/call/room-token",
            {"flags": 3, "silent": False, "recordingConsent": False},
        )
    ]


@pytest.mark.asyncio
async def test_update_media_call_flags_uses_put(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NextcloudTalkClient("https://cloud.test", "bot", "app-password")
    calls: list[tuple[str, str, object]] = []

    async def unavailable_web_request(*_: object, **__: object) -> None:
        raise RuntimeError("unavailable")

    async def fake_request(method: str, endpoint: str, **kwargs: object) -> dict[str, bool]:
        calls.append((method, endpoint, kwargs.get("data")))
        return {"ok": True}

    monkeypatch.setattr(client, "_web_request", unavailable_web_request)
    monkeypatch.setattr(client, "_request", fake_request)

    assert await client.update_media_call_flags("room-token", flags=3) == {"ok": True}
    assert calls == [
        (
            "PUT",
            "/ocs/v2.php/apps/spreed/api/v4/call/room-token",
            {"flags": 3},
        )
    ]


@pytest.mark.asyncio
async def test_join_media_call_matches_android_form_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = NextcloudTalkClient("https://cloud.test", "bot", "app-password")
    calls: list[tuple[str, str, object]] = []

    async def unavailable_web_request(*_: object, **__: object) -> None:
        raise RuntimeError("unavailable")

    async def fake_request(method: str, endpoint: str, **kwargs: object) -> dict[str, bool]:
        calls.append((method, endpoint, kwargs.get("data")))
        return {"ok": True}

    monkeypatch.setattr(client, "_web_request", unavailable_web_request)
    monkeypatch.setattr(client, "_request", fake_request)

    await client.join_media_call(
        "room-token",
        flags=3,
        silent=True,
        recording_consent=True,
    )

    assert calls == [
        (
            "POST",
            "/ocs/v2.php/apps/spreed/api/v4/call/room-token",
            {"flags": 3, "silent": True, "recordingConsent": True},
        )
    ]


@pytest.mark.asyncio
async def test_leave_media_call_matches_android_all_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = NextcloudTalkClient("https://cloud.test", "bot", "app-password")
    calls: list[tuple[str, str, object]] = []

    async def unavailable_web_request(*_: object, **__: object) -> None:
        raise RuntimeError("unavailable")

    async def fake_request(method: str, endpoint: str, **kwargs: object) -> dict[str, bool]:
        calls.append((method, endpoint, kwargs.get("params")))
        return {"ok": True}

    monkeypatch.setattr(client, "_web_request", unavailable_web_request)
    monkeypatch.setattr(client, "_request", fake_request)

    await client.leave_media_call("room-token")
    await client.leave_media_call("room-token", all_participants=True)

    assert calls == [
        (
            "DELETE",
            "/ocs/v2.php/apps/spreed/api/v4/call/room-token",
            {"all": False},
        ),
        (
            "DELETE",
            "/ocs/v2.php/apps/spreed/api/v4/call/room-token",
            {"all": True},
        ),
    ]


@pytest.mark.asyncio
async def test_join_call_prefers_web_session(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NextcloudTalkClient(
        "https://cloud.test",
        "bot",
        "app-password",
    )
    calls: list[tuple[str, str, object]] = []

    async def fake_web_request(method: str, endpoint: str, **kwargs: object) -> dict[str, str]:
        calls.append((method, endpoint, kwargs.get("data")))
        return {"sessionId": "web-session"}

    async def fake_basic_request(method: str, endpoint: str, **_: object) -> dict[str, str]:
        raise AssertionError("participants/active should prefer web session over Basic Auth")

    monkeypatch.setattr(client, "_web_request", fake_web_request)
    monkeypatch.setattr(client, "_request", fake_basic_request)

    assert await client.join_call("room-token") == {"sessionId": "web-session"}
    assert calls == [
        (
            "POST",
            "/ocs/v2.php/apps/spreed/api/v4/room/room-token/participants/active",
            {},
        )
    ]


@pytest.mark.asyncio
async def test_signaling_settings_prefers_web_session(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NextcloudTalkClient(
        "https://cloud.test",
        "bot",
        "app-password",
    )
    calls: list[tuple[str, str, object]] = []

    async def fake_web_request(method: str, endpoint: str, **kwargs: object) -> dict[str, str]:
        calls.append((method, endpoint, kwargs.get("params")))
        return {"server": "wss://hpb.test/spreed"}

    async def fake_basic_request(method: str, endpoint: str, **_: object) -> dict[str, str]:
        raise AssertionError("signaling settings should prefer web session over Basic Auth")

    monkeypatch.setattr(client, "_web_request", fake_web_request)
    monkeypatch.setattr(client, "_request", fake_basic_request)

    assert await client.get_signaling_settings("room-token") == {"server": "wss://hpb.test/spreed"}
    assert calls == [
        (
            "GET",
            "/ocs/v2.php/apps/spreed/api/v3/signaling/settings",
            {"token": "room-token"},
        )
    ]
