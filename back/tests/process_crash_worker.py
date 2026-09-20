"""Fault-injection subprocess used only against committed_database clones."""

import asyncio
import json
import os
from pathlib import Path
import signal
import sys
from types import SimpleNamespace
from uuid import UUID


async def main():
    if os.environ.get("APP_ENV") != "test" or not os.environ.get("POSTGRES_DB", "").startswith("test_concurrency_"):
        raise RuntimeError("Crash probes require a disposable test database clone")
    import main as application  # Registers the same models and domain ports as production.
    from core.database import get_db_session
    from app.process import process_service, registry
    from app.process.schemas import EngineStartResult, ProcessCallbackEvent
    from app.task import collab, runner

    del application
    mode, identifier, receipt_path, crash = sys.argv[1:]
    run_id = UUID(identifier)
    # The scheduler is a separate boundary, not part of the callback transaction.
    runner.go_next = lambda *args, **kwargs: None

    def stop():
        os.kill(os.getpid(), signal.SIGKILL)

    if mode == "callback":
        if crash == "crash":
            async def interrupted_fan_in(**kwargs):
                stop()
            collab.resolve_process_await = interrupted_fan_in
        async with get_db_session():
            await process_service.receive_callback(run_id, "token", ProcessCallbackEvent(
                event_id="durable-completion", status="success", output={"receipt": "kept"},
            ))
    elif mode == "admission":
        receipt = Path(receipt_path)

        async def start(_workflow, reference, _payload):
            # Simulated external provider with a durable idempotency ledger.
            # It survives the Galaris worker; this does not certify a real provider.
            key = reference.correlation_id
            ledger = json.loads(receipt.read_text()) if receipt.exists() else {"requests": [], "effects": {}}
            ledger["requests"].append(key)
            ledger["effects"].setdefault(key, "remote-effect")
            with receipt.open("w") as output:
                json.dump(ledger, output)
                output.flush()
                os.fsync(output.fileno())
            if crash == "crash":
                stop()
            return EngineStartResult(accepted=True, engine_run_id=ledger["effects"][key])

        registry._engines["crash-test"] = SimpleNamespace(start_run=start)
        async with get_db_session():
            await process_service.process_start_jobs(engine_code="crash-test", batch_size=1)
    else:
        raise ValueError(mode)


if __name__ == "__main__":
    asyncio.run(main())
