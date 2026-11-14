"""Calendar connections support enterprise networks without losing transport boundaries."""

import asyncio
import socket

import httpx
import pytest

from app.file_share import ResourceUriError
from bridge.calendar import transport


URL = 'https://calendar.example.test:8443/agenda.ics'
CALENDAR = b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n'


def dns_answers(monkeypatch, *addresses):
    async def getaddrinfo(host, port, **kwargs):
        return [
            (socket.AF_INET6 if ':' in address else socket.AF_INET,
             socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, port))
            for address in addresses
        ]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', getaddrinfo)


def http_provider(monkeypatch, handler):
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs['trust_env'] is False
        assert kwargs.get('verify', True) is True
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(transport.httpx, 'AsyncClient', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('address', [
    '10.20.30.40', '172.20.0.5', '192.168.1.5', 'fd12:3456::5', 'fc00::5',
    '::ffff:10.20.30.40', '1.1.1.1', '2606:4700:4700::1111',
])
@pytest.mark.parametrize('literal', [False, True], ids=['hostname', 'ip-literal'])
async def test_calendar_reads_public_and_private_networks_with_dns_pinning(monkeypatch, address, literal):
    dns_answers(monkeypatch, address)
    host = (f'[{address}]' if ':' in address else address) if literal else 'calendar.example.test'
    url = f'https://{host}:8443/agenda.ics'
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=CALENDAR)
    http_provider(monkeypatch, handler)

    response = await transport.read_calendar(url)

    assert response.content == CALENDAR and response.final_url == url
    assert len(requests) == 1
    assert requests[0].url.host == address
    assert requests[0].url.port == 8443
    assert requests[0].headers['host'] == f'{host}:8443'
    assert requests[0].extensions['sni_hostname'] == (address if literal else 'calendar.example.test')


@pytest.mark.asyncio
@pytest.mark.parametrize('address', [
    '127.0.0.1', '::1', '169.254.169.254', 'fe80::1', '0.0.0.0', '::',
    '224.0.0.1', 'ff02::1', '255.255.255.255', '::ffff:127.0.0.1',
    '::ffff:169.254.169.254',
])
async def test_calendar_rejects_special_addresses_before_http_even_with_other_dns_answers(monkeypatch, address):
    dns_answers(monkeypatch, '1.1.1.1', '10.20.30.40', address)
    def handler(request):
        pytest.fail('A forbidden DNS answer must prevent the HTTP request')
    http_provider(monkeypatch, handler)

    with pytest.raises(ResourceUriError):
        await transport.read_calendar(URL)


@pytest.mark.asyncio
async def test_private_calendar_redirect_does_not_forward_credentials_to_another_origin(monkeypatch):
    dns_answers(monkeypatch, '10.20.30.40')
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={'Location': 'https://other.example.test/agenda.ics'})
        return httpx.Response(200, content=CALENDAR)
    http_provider(monkeypatch, handler)

    await transport.read_calendar(URL, username='synthetic', password='synthetic-password')

    assert len(requests) == 2
    assert 'authorization' in requests[0].headers
    assert 'authorization' not in requests[1].headers


@pytest.mark.asyncio
async def test_icloud_discovery_permits_only_validated_apple_shards_and_scopes_credentials(monkeypatch):
    dns_answers(monkeypatch, '1.1.1.1')
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(302, headers={'Location': 'https://p42-caldav.icloud.com/account/'})
        return httpx.Response(207, content=b'<multistatus/>')
    http_provider(monkeypatch, handler)
    with transport.calendar_authorization(None, icloud=True):
        await transport.request_calendar('PROPFIND', 'https://caldav.icloud.com/', username='synthetic-apple', password='synthetic-app-password')
        for target in ('https://p42-caldav.icloud.com.evil.test/', 'https://evil.icloud.com/', 'https://p42-caldav.icloud.com:8443/', 'http://p42-caldav.icloud.com/'):
            assert not transport.same_calendar_origin('https://caldav.icloud.com/', target)
    assert len(calls) == 2 and calls[0].headers['authorization'] == calls[1].headers['authorization']
    assert not transport.same_calendar_origin('https://caldav.icloud.com/', 'https://p42-caldav.icloud.com/')


@pytest.mark.asyncio
async def test_caldav_bearer_is_scoped_and_not_forwarded_on_cross_origin_redirect(monkeypatch):
    dns_answers(monkeypatch, '10.20.30.40')
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={'Location': 'https://other.example.test/feed'}) if len(calls) == 1 else httpx.Response(200, content=CALENDAR)
    http_provider(monkeypatch, handler)
    with transport.calendar_authorization('synthetic-oauth-token'):
        await transport.read_calendar(URL, username='ignored', password='ignored')
    await transport.read_calendar(URL)
    assert calls[0].headers['authorization'] == 'Bearer synthetic-oauth-token'
    assert all('authorization' not in call.headers for call in calls[1:])


@pytest.mark.asyncio
async def test_calendar_revalidates_dns_after_a_redirect(monkeypatch):
    dns_answers(monkeypatch, '10.20.30.40')
    requests = []
    def handler(request):
        requests.append(request)
        dns_answers(monkeypatch, '169.254.169.254')
        return httpx.Response(302, headers={'Location': '/redirected.ics'})
    http_provider(monkeypatch, handler)

    with pytest.raises(ResourceUriError):
        await transport.read_calendar(URL)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['PROPFIND', 'REPORT', 'PUT', 'DELETE'])
async def test_private_dav_requests_reject_unsafe_redirects(monkeypatch, method):
    dns_answers(monkeypatch, '10.20.30.40')
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={'Location': 'https://other.example.test/agenda/'})
    http_provider(monkeypatch, handler)

    with pytest.raises(ValueError, match='redirect'):
        await transport.request_calendar(method, URL, username='synthetic', password='synthetic-password')
    assert len(requests) == 1
