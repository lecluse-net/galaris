import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.util.editorial_client import require_editorial_client


def request(body, version=None):
    async def receive():
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    return Request(
        {
            "type": "http",
            "headers": []
            if version is None
            else [(b"x-editorial-profile-version", version.encode())],
        },
        receive=receive,
    )


@pytest.mark.asyncio
async def test_cached_editor_is_rejected_before_any_editorial_mutation():
    with pytest.raises(HTTPException) as failure:
        await require_editorial_client(request({"objective": "old Markdown"}))
    assert failure.value.status_code == 409
    await require_editorial_client(request({"objective": "<p>HTML</p>"}, "1"))
    await require_editorial_client(request({"title": "A metadata-only rename"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, "0", "1"])
async def test_upload_negotiation_preserves_consumed_multipart_streams(version):
    upload = request({}, version)
    upload.scope["headers"].append((b"content-type", b"multipart/form-data; boundary=synthetic"))
    async for _chunk in upload.stream():
        pass
    if version == "1":
        await require_editorial_client(upload)
    else:
        with pytest.raises(HTTPException) as failure:
            await require_editorial_client(upload)
        assert failure.value.status_code == 409
