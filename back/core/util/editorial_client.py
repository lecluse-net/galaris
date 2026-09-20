"""HTTP capability negotiation for applications switching to editorial HTML."""

from fastapi import HTTPException, Request
from typing import cast


async def require_editorial_client(request: Request) -> None:
    """Reject cached clients before they can flatten an existing rich document."""
    body: object = await request.json()
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
        isinstance(body, dict)
        and fields.intersection(cast(dict[str, object], body))
        and request.headers.get("x-editorial-profile-version") != "1"
    ):
        raise HTTPException(
            status_code=409,
            detail="Editorial HTML profile 1 is required. Reload the application and preserve your draft before retrying.",
        )
