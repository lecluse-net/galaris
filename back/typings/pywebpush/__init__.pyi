from collections.abc import Mapping

class WebPushException(Exception):
    response: object | None

def webpush(
    subscription_info: Mapping[str, object],
    data: str | None = ...,
    vapid_private_key: object | str | None = ...,
    vapid_claims: dict[str, str | int] | None = ...,
    content_encoding: str = ...,
    curl: bool = ...,
    timeout: float | None = ...,
    ttl: int = ...,
    verbose: bool = ...,
    headers: dict[str, str | int | float] | None = ...,
    requests_session: object | None = ...,
) -> object: ...
