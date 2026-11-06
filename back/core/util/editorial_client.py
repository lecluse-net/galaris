"""HTTP capability negotiation for applications switching to editorial HTML."""

from fastapi import HTTPException, Request
from typing import cast


async def require_editorial_client(request: Request) -> None:
    """Reject cached clients before they can flatten an existing rich document."""
    # FastAPI has already consumed multipart streams while parsing UploadFile.
    # Uploads still require explicit negotiation, without trying to reread JSON.
    multipart = request.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "multipart/form-data"
    body: object = None if multipart else await request.json()
    fields = {
        "personality",
        "job_description",
        "objective",
        "description",
        "tracking_content",
        "payload",
        "content",
    }
    if (
        (multipart or isinstance(body, dict) and fields.intersection(cast(dict[str, object], body)))
        and request.headers.get("x-editorial-profile-version") != "1"
    ):
        raise HTTPException(
            status_code=409,
            detail="Editorial HTML profile 1 is required. Reload the application and preserve your draft before retrying.",
        )
