"""Network trust boundaries use synthetic addresses and no live public services."""

import asyncio
import gzip
import socket

import httpx
import pytest

from app.tools.admin_network import PinnedMcpTransport, origin, resolve_destination


@pytest.mark.parametrize("address", ["169.254.169.254", "::ffff:169.254.169.254", "100.100.100.200", "168.63.129.16", "0.0.0.0", "224.0.0.1"])
@pytest.mark.asyncio
async def test_prohibited_destination_even_when_private_is_authorized(monkeypatch, address):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ValueError, match="prohibited"):
        await resolve_destination("http://mcp.example.test/mcp", allow_private=True)


@pytest.mark.asyncio
async def test_private_destination_requires_human_authorization_and_checks_every_dns_result(monkeypatch):
    addresses = ["10.2.3.4"]
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80)) for address in addresses]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ValueError, match="human-prepared"):
        await resolve_destination("http://mcp.example.test/mcp", allow_private=False)
    assert await resolve_destination("http://mcp.example.test/mcp", allow_private=True) == "10.2.3.4"
    addresses.append("169.254.169.254")
    with pytest.raises(ValueError, match="prohibited"):
        await resolve_destination("http://mcp.example.test/mcp", allow_private=True)


@pytest.mark.asyncio
async def test_pinned_transport_preserves_host_and_refuses_redirect_and_cross_origin():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://other.example.test/"})
    transport = PinnedMcpTransport("https://mcp.example.test/mcp", "192.0.2.10")
    await transport.transport.aclose()
    transport.transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport, headers={"Authorization": "Bearer synthetic"}) as client:
        with pytest.raises(ValueError, match="cross-origin"):
            await client.post("https://other.example.test/post")
        assert requests == []
        with pytest.raises(ValueError, match="redirects"):
            await client.post("https://mcp.example.test/mcp")
    assert len(requests) == 1
    assert requests[0].url.host == "192.0.2.10"
    assert requests[0].headers["host"] == "mcp.example.test"
    assert requests[0].extensions["sni_hostname"] == "mcp.example.test"


@pytest.mark.parametrize("url", ["file:///tmp/config", "http://user:synthetic@example.test/mcp", "https://example.test/mcp?token=synthetic", "https://example.test/mcp#fragment"])
def test_urls_cannot_carry_credentials(url):
    with pytest.raises(ValueError):
        origin(url)


@pytest.mark.asyncio
async def test_compression_cannot_bypass_the_response_byte_limit():
    compressed = gzip.compress(b"x" * (3 * 1024 * 1024))
    transport = PinnedMcpTransport("https://mcp.example.test/mcp", "192.0.2.10")
    await transport.transport.aclose()
    transport.transport = httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(compressed),
    ))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="compression"):
            await client.get("https://mcp.example.test/mcp")
