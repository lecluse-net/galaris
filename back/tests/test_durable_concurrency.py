"""Independent PostgreSQL transactions for bounded durable queues and receipts."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from core.database import get_db_session
from core.user.models import User
from app.agent.models import Agent, Title
from app.tools.models import Tool
from app.process.models import ProcessDefinition, ProcessRun

async def seed_run():
    async with get_db_session() as db:
        code = uuid4().hex
        user = User(email=f"{code}@example.test", hashed_password="unused", is_active=True)
        title = Title(label=code, gender="X")
        tool = Tool(code=code, label=code, connection_schema={})
        db.add_all([user, title, tool]); await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=code, first_name="Concurrent", last_name="Test")
        db.add(agent); await db.flush()
        definition = ProcessDefinition(agent_id=agent.id, tool_id=tool.id, engine_process_id=code, label=code)
        db.add(definition); await db.flush()
        run = ProcessRun(process_id=definition.id, launcher_agent_id=agent.id, engine_code="multimedia",
            correlation_id=code, callback_token="unused", status="running", input={})
        db.add(run); await db.flush()
        return agent.id, run.id

@pytest.mark.asyncio
async def test_concurrent_media_receipts_are_unique_and_protected_until_delivered(committed_database, monkeypatch):
    from app.llm import MediaArtifact, MediaResult
    from app.multimedia import engine as module
    from app.multimedia import provider_results
    from app.multimedia.models import MediaOutputReceipt
    from app.process import retention
    from core.params import runtime_settings
    _, run_id = await seed_run()
    waiting = 0
    both = asyncio.Event()
    async def download(*_a, **_k):
        nonlocal waiting
        waiting += 1
        if waiting == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 5)
        return SimpleNamespace(content=b"ID3same-output")
    monkeypatch.setattr(provider_results, "read_public_https_bytes", download)
    result = MediaResult(state="success", artifacts=[MediaArtifact(external_id="output-1", media_type="audio/mpeg", url="https://example.test/output")])
    async def receive(value):
        async with get_db_session():
            await module.MultimediaEngine()._receive(run_id, value)
    await asyncio.gather(receive(result), receive(result))
    async with get_db_session() as db:
        receipts = list(await db.scalars(select(MediaOutputReceipt).where(MediaOutputReceipt.run_id == run_id)))
        assert len(receipts) == 1 and receipts[0].content == b"ID3same-output"
    changed = MediaResult(state="success", artifacts=[MediaArtifact(external_id="other", media_type="audio/mpeg", content=b"ID3different")])
    with pytest.raises(ValueError, match="cannot change"):
        await receive(changed)
    monkeypatch.setattr(retention, "_guards", {"receipt": lambda: select(MediaOutputReceipt.run_id).where(MediaOutputReceipt.content.is_not(None))})
    monkeypatch.setattr(runtime_settings, "PROCESS_RETENTION_RUN_DAYS", 1)
    async with get_db_session() as db:
        run = await db.get(ProcessRun, run_id)
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc) - timedelta(days=400)
    async with get_db_session() as db:
        await retention.purge_retention()
        assert await db.get(ProcessRun, run_id) is not None

@pytest.mark.asyncio
@pytest.mark.parametrize("item_count", [601, 10_001])
async def test_concurrent_semantic_rebuild_creates_one_job_per_item(committed_database, monkeypatch, item_count):
    from app.memory import semantic_index
    from app.memory.embedding import EmbeddingModel
    from app.memory.models import MemoryItem, MemoryAutomationJob
    agent_id, _ = await seed_run()
    prefix = uuid4().hex
    async with get_db_session() as db:
        db.add_all([MemoryItem(owner_agent_id=agent_id, resource_id=f"{prefix}/{i}",
            title=f"Memory {i}", content_hash=f"{i:064x}") for i in range(item_count)])
    model = EmbeddingModel(key=prefix, code="concurrent", model_name="test", base_url="http://embedding.invalid", api_key=None)
    monkeypatch.setattr(semantic_index, "resolve_embedding_model", AsyncMock(return_value=model))
    async def reconcile():
        async with get_db_session():
            return await semantic_index.reconcile_embedding_index()
    first, second = await asyncio.gather(reconcile(), reconcile())
    assert first.scanned == second.scanned and first.scanned >= item_count
    async with get_db_session() as db:
        count = await db.scalar(select(func.count(MemoryAutomationJob.id)).where(MemoryAutomationJob.payload["model_key"].astext == prefix))
        assert count == first.scanned

@pytest.mark.asyncio
async def test_buffered_saturation_leaves_auth_files_and_lease_renewal_operational(committed_database, monkeypatch, tmp_path):
    from httpx import ASGITransport, AsyncClient
    from core.database import middleware
    from core.user.user_service import encrypt_password
    from core.util import ByteBudget, copy_download
    from app.task import Task, TaskStatus, scheduler
    from core.params import runtime_settings
    from main import app
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "TASK_SCHEDULER_LEASE_SECONDS", 30)
    token = uuid4()
    start = datetime.now(timezone.utc)
    async with get_db_session() as db:
        user = User(email=f"mixed-{uuid4()}@example.com", hashed_password=encrypt_password("Mixed-load-password-42!"), is_active=True)
        task = Task(label="Mixed load heartbeat", status=TaskStatus.PLAN, lease_token=token,
            lease_expires_at=start + timedelta(seconds=30))
        db.add_all([user, task]); await db.flush()
        email, task_id = user.email, task.id
    from aiortc import RTCPeerConnection, RTCConfiguration
    from bridge.nextcloud.call import _build_out_track
    from core.util import buffered_io_budget
    import base64
    import json
    import psutil
    import time
    import os

    load_seconds = float(os.environ.get("MIXED_LOAD_SECONDS", "0"))
    assert 0 <= load_seconds <= 120
    load_until = time.monotonic() + load_seconds

    peers = [RTCPeerConnection(RTCConfiguration(iceServers=[])) for _ in range(2)]
    track = _build_out_track()
    peers[0].addTrack(track)
    received = asyncio.get_running_loop().create_future()
    peers[1].on("track", lambda remote: received.set_result(remote))
    await peers[0].setLocalDescription(await peers[0].createOffer())
    await peers[1].setRemoteDescription(peers[0].localDescription)
    await peers[1].setLocalDescription(await peers[1].createAnswer())
    await peers[0].setRemoteDescription(peers[1].localDescription)
    remote = await asyncio.wait_for(received, 5)
    frame_count = 0
    process = psutil.Process()
    initial_rss = process.memory_info().rss
    peak_rss = initial_rss
    latencies = []
    max_loop_lag = 0.0
    async def receive_audio():
        nonlocal frame_count
        while True:
            await remote.recv()
            frame_count += 1
    async def encode_media():
        async with buffered_io_budget.reserve(64 * 1024 * 1024, owner="mixed-encoding"):
            content = b"a" * (16 * 1024 * 1024)
            iteration = 0
            while iteration < 20 or time.monotonic() < load_until:
                iteration += 1
                encoded = await asyncio.to_thread(base64.b64encode, content)
                assert len(encoded) > len(content)
                del encoded
                await asyncio.sleep(0.01)
    async def observe_pressure():
        nonlocal peak_rss, max_loop_lag
        while True:
            started = time.monotonic()
            await asyncio.sleep(0.02)
            max_loop_lag = max(max_loop_lag, time.monotonic() - started - 0.02)
            peak_rss = max(peak_rss, process.memory_info().rss)
    audio_reader = asyncio.create_task(receive_audio())
    encoding = asyncio.create_task(encode_media())
    pressure = asyncio.create_task(observe_pressure())
    budget = ByteBudget(100)
    peak = 0
    async def blocked_media(index):
        nonlocal peak
        async with budget.reserve(60, owner=str(index), timeout=max(10, load_seconds + 10)):
            peak = max(peak, budget.used)
            await asyncio.sleep(0.01)
    async def chunks():
        for _ in range(64):
            yield b"a" * 65536
            await asyncio.sleep(0)
    heartbeat = asyncio.create_task(scheduler._heartbeat_lease(task_id, token))
    queued = []
    try:
        async with budget.reserve(100, owner="provider-waiting"):
            queued = [asyncio.create_task(blocked_media(i)) for i in range(8)]
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http:
                async with asyncio.timeout(5):
                    login = await http.post("/api/auth/login", data={"username": email, "password": "Mixed-load-password-42!"})
                    assert login.status_code == 200, login.text
                    access = login.json()["access_token"]
                    async def read_identity():
                        started = time.monotonic()
                        response = await http.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
                        latencies.append(time.monotonic() - started)
                        return response
                    responses = await asyncio.gather(*(read_identity() for _ in range(32)))
                    assert all(response.status_code == 200 for response in responses)
                    assert await copy_download(chunks(), tmp_path / "mixed", max_bytes=4 * 1024 * 1024) == 4 * 1024 * 1024
                async with asyncio.timeout(8):
                    while True:
                        async with get_db_session() as db:
                            expires = await db.scalar(select(Task.lease_expires_at).where(Task.id == task_id))
                        if expires > start + timedelta(seconds=31):
                            break
                        await asyncio.sleep(0.1)
                while time.monotonic() < load_until:
                    responses = await asyncio.gather(*(read_identity() for _ in range(4)))
                    assert all(response.status_code == 200 for response in responses)
                    await asyncio.sleep(0.2)
            assert budget.used == 100 and peak == 0
        await asyncio.gather(*queued)
        assert peak == 60 and budget.used == 0
        await encoding
        assert frame_count >= 100
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        rss_growth = peak_rss - initial_rss
        assert p95 < 2.0 and max_loop_lag < 1.0
        assert rss_growth < 256 * 1024 * 1024
        print("MIXED_LOAD=" + json.dumps({"identity_p95_seconds": p95, "peak_rss_growth_bytes": rss_growth,
            "loop_max_lag_seconds": max_loop_lag, "received_webrtc_frames": frame_count,
            "lease_renewed": True, "file_bytes": 4 * 1024 * 1024}))
    finally:
        heartbeat.cancel()
        for pending in queued:
            pending.cancel()
        for worker in (audio_reader, encoding, pressure):
            worker.cancel()
        await asyncio.gather(heartbeat, *queued, audio_reader, encoding, pressure, return_exceptions=True)
        await asyncio.gather(*(peer.close() for peer in peers))


@pytest.mark.asyncio
async def test_progress_age_includes_unobserved_runs_without_using_old_creation_of_observed_runs(committed_database, monkeypatch):
    from app.process import progress
    _, observed_id = await seed_run()
    _, unobserved_id = await seed_run()
    now = datetime.now(timezone.utc)
    async with get_db_session() as db:
        observed = await db.get(ProcessRun, observed_id)
        observed.created_at = now - timedelta(seconds=1000)
        observed.engine_metadata = {"last_observed_at": now.isoformat()}
        unobserved = await db.get(ProcessRun, unobserved_id)
        unobserved.created_at = now - timedelta(seconds=100)
        unobserved.status = "unknown"
    values = {}
    monkeypatch.setattr(progress.registry, "codes", lambda: ["multimedia"])
    for name in ("_queue_age", "_pending", "_unknown", "_observation_age"):
        monkeypatch.setattr(progress, name, SimpleNamespace(set=lambda value, labels=None, name=name: values.update({name: value})))
    async with get_db_session():
        await progress.record_progress_metrics()
    assert values["_unknown"] == 1
    assert 90 < values["_observation_age"] < 200


@pytest.mark.asyncio
async def test_malformed_optional_observation_does_not_break_metrics(committed_database, monkeypatch):
    from app.process import progress
    _, run_id = await seed_run()
    async with get_db_session() as db:
        run = await db.get(ProcessRun, run_id)
        run.created_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        run.engine_metadata = {"last_observed_at": "not-a-date-from-an-old-engine"}
    observed = []
    monkeypatch.setattr(progress.registry, "codes", lambda: ["multimedia"])
    monkeypatch.setattr(progress, "_observation_age", SimpleNamespace(set=lambda value, labels: observed.append(value)))
    async with get_db_session():
        await progress.record_progress_metrics()
    assert 55 < observed[0] < 90
