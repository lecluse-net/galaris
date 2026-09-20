import pytest
import httpx

from app.file_share import web_transport
from app.file_share.resource_uri import ResourceUriError


class _ResolverLoop:
    def __init__(self, *addresses: str) -> None:
        self.addresses = addresses

    async def getaddrinfo(self, *_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (None, None, None, None, (address, 443))
            for address in self.addresses
        ]


@pytest.mark.asyncio
async def test_https_transport_rejects_private_dns_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_transport.asyncio,
        "get_running_loop",
        lambda: _ResolverLoop("127.0.0.1"),
    )

    with pytest.raises(ResourceUriError, match="non-public"):
        await web_transport._resolve_public_https("https://files.example/report.pdf")


@pytest.mark.asyncio
async def test_https_transport_accepts_public_dns_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_transport.asyncio,
        "get_running_loop",
        lambda: _ResolverLoop("1.1.1.1"),
    )

    target = await web_transport._resolve_public_https(
        "https://files.example/report.pdf"
    )

    assert target.url == "https://files.example/report.pdf"
    assert target.hostname == "files.example"
    assert target.addresses == ("1.1.1.1",)


@pytest.mark.asyncio
async def test_https_transport_rejects_a_mixed_public_and_private_dns_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_transport.asyncio,
        "get_running_loop",
        lambda: _ResolverLoop("1.1.1.1", "10.0.0.8"),
    )

    with pytest.raises(ResourceUriError, match="non-public"):
        await web_transport._resolve_public_https("https://files.example/report.pdf")


@pytest.mark.asyncio
async def test_https_transport_connects_to_the_validated_address_with_original_tls_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, content=b"safe", request=request)

    async def resolve(_value: str) -> web_transport._ResolvedHttpsTarget:
        return web_transport._ResolvedHttpsTarget(
            url="https://files.example:8443/report.pdf?download=1",
            hostname="files.example",
            host_header="files.example:8443",
            addresses=("1.1.1.1",),
        )

    monkeypatch.setattr(web_transport, "_resolve_public_https", resolve)
    monkeypatch.setattr(
        web_transport,
        "_new_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    client, response, final_url = await web_transport.PublicHttpsFileTransport()._request(
        "GET",
        "https://files.example:8443/report.pdf?download=1",
        stream=True,
    )
    try:
        assert await response.aread() == b"safe"
    finally:
        await response.aclose()
        await client.aclose()

    assert final_url == "https://files.example:8443/report.pdf?download=1"
    assert len(requested) == 1
    assert str(requested[0].url) == "https://1.1.1.1:8443/report.pdf?download=1"
    assert requested[0].headers["host"] == "files.example:8443"
    assert requested[0].extensions["sni_hostname"] == "files.example"
