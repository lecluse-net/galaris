import pytest

from bridge.hermes import client


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"run_id": "run-1", "ok": True}


class _StatusResponse(_FakeResponse):
    def __init__(self, status_code: int):
        self.status_code = status_code


class _CapturingAsyncClient:
    urls: list[str] = []
    requests: list[tuple[str, dict[str, object]]] = []
    response_status = 200

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, **kwargs):
        self.urls.append(url)
        self.requests.append((url, kwargs))
        return _StatusResponse(self.response_status)

    async def get(self, url, **kwargs):
        self.urls.append(url)
        self.requests.append((url, kwargs))
        return _FakeResponse()


@pytest.mark.asyncio
async def test_run_endpoints_accept_base_url_with_or_without_v1(monkeypatch):
    _CapturingAsyncClient.urls = []
    _CapturingAsyncClient.requests = []
    _CapturingAsyncClient.response_status = 200
    monkeypatch.setattr(client.httpx, "AsyncClient", _CapturingAsyncClient)

    with_v1 = client.HermesTarget(
        url="http://aster-test-agent:8642/v1",
        api_key="test-key",
        model="test-model",
    )
    without_v1 = client.HermesTarget(
        url="http://aster-test-agent:8642",
        api_key="test-key",
        model="test-model",
    )

    await client.start_run(
        with_v1,
        session_id="session-1",
        session_key="galaris_key_stable",
        message="hello",
    )
    await client.get_run_status(with_v1, "run-1")
    await client.stop_run(with_v1, "run-1")
    await client.submit_run_approval(with_v1, "run-1", "approve")
    await client.start_run(without_v1, session_id="session-2", message="hello")

    assert _CapturingAsyncClient.urls == [
        "http://aster-test-agent:8642/v1/runs",
        "http://aster-test-agent:8642/v1/runs/run-1",
        "http://aster-test-agent:8642/v1/runs/run-1/stop",
        "http://aster-test-agent:8642/v1/runs/run-1/approval",
        "http://aster-test-agent:8642/v1/runs",
    ]
    first_headers = _CapturingAsyncClient.requests[0][1]["headers"]
    assert first_headers["X-Hermes-Session-Key"] == "galaris_key_stable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (404, client.HermesRunNotFound),
        (409, client.HermesApprovalNotPending),
    ],
)
async def test_submit_run_approval_rejects_terminal_responses_without_replay(
    monkeypatch,
    status_code,
    expected_error,
):
    _CapturingAsyncClient.response_status = status_code
    monkeypatch.setattr(client.httpx, "AsyncClient", _CapturingAsyncClient)
    target = client.HermesTarget(
        url="http://hermes:8642/v1",
        api_key="test-key",
        model="test-model",
    )

    with pytest.raises(expected_error):
        await client.submit_run_approval(target, "run-gone", "once")


def test_hermes_target_repr_hides_api_key():
    target = client.HermesTarget(
        url="http://hermes:8642/v1",
        api_key="super-secret-value",
        model="test-model",
    )

    rendered = repr(target)

    assert "super-secret-value" not in rendered
    assert "api_key" not in rendered


@pytest.mark.asyncio
async def test_session_ids_are_url_encoded(monkeypatch):
    _CapturingAsyncClient.urls = []
    _CapturingAsyncClient.requests = []
    _CapturingAsyncClient.response_status = 200
    monkeypatch.setattr(client.httpx, "AsyncClient", _CapturingAsyncClient)
    target = client.HermesTarget(
        url="http://hermes:8642/v1",
        api_key="test-key",
        model="test-model",
    )

    await client.get_session(target, "tip/with ? characters")
    await client.get_session_messages(target, "tip/with ? characters")

    assert _CapturingAsyncClient.urls == [
        "http://hermes:8642/api/sessions/tip%2Fwith%20%3F%20characters",
        "http://hermes:8642/api/sessions/tip%2Fwith%20%3F%20characters/messages",
    ]
