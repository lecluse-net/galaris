"""Synthetic OneBot peer speaking real reverse WebSocket frames to the assembled API."""
import asyncio
import json
import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import uvicorn
import websockets


@asynccontextmanager
async def connected_adapter(*, token="synthetic-token"):
    from main import app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error", timeout_graceful_shutdown=1))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.01)
        uri = f"ws://127.0.0.1:{sock.getsockname()[1]}/ws/onebot/qq/700"
        async with websockets.connect(uri, additional_headers={
            "Authorization": f"Bearer {token}", "X-Self-ID": "700", "X-Client-Role": "Universal",
        }) as ws:
            peer = SimpleNamespace(socket=ws, uri=uri, send_text=AsyncMock(), actions=[])

            async def respond():
                async for raw in ws:
                    request = json.loads(raw)
                    action = request["action"]
                    peer.actions.append(action)
                    status, retcode, data = "ok", 0, []
                    if action in {"send_private_msg", "send_group_msg"}:
                        await peer.send_text(request["params"])
                        data = {"message_id": 9900 + peer.send_text.await_count}
                    elif action == "get_login_info":
                        data = {"user_id": 700, "nickname": "Synthetic Bot"}
                    elif action == "get_friend_list":
                        data = [{"user_id": 420, "nickname": "Synthetic Contact"}]
                    elif action != "get_group_list":
                        status, retcode, data = "failed", 1404, None
                    await ws.send(json.dumps({"echo": request["echo"], "status": status,
                        "retcode": retcode, "data": data}))

            responding = asyncio.create_task(respond())
            try:
                yield peer
            finally:
                responding.cancel()
                await asyncio.gather(responding, return_exceptions=True)
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 5)
        sock.close()
