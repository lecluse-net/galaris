import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_liveness_check(client: AsyncClient) -> None:
    response = await client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime_status", "expected_status"),
    (("ready", 200), ("degraded", 200), ("not_ready", 503)),
)
async def test_readiness_status_code(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    runtime_status: str,
    expected_status: int,
) -> None:
    from core import runtime

    class FakeSupervisor:
        async def readiness_report(self) -> dict[str, object]:
            return {"status": runtime_status, "checks": {}}

    monkeypatch.setattr(runtime, "runtime_supervisor", FakeSupervisor())

    response = await client.get("/api/health/ready")

    assert response.status_code == expected_status
    assert response.json() == {"status": runtime_status, "checks": {}}
