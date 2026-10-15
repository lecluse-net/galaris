"""Exercise the downloadable relay with a real local HTTP callback."""

import runpy
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from app.connection import oauth_loopback


@pytest.mark.parametrize("answer", [{"code": "synthetic-private-code"}, {"error": "access_denied"}])
def test_downloaded_relay_checks_callback_and_returns_to_private_galaris(tmp_path, monkeypatch, capsys, answer):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    callback = f"http://127.0.0.1:{port}/oauth/callback"
    state = "synthetic-state-for-workstation-000001"
    authorization = "https://oauth.example.test/authorize?" + urlencode({"redirect_uri": callback, "state": state})
    return_url = "https://private.example.test/connection/oauth-callback"
    script = tmp_path / "galaris-connect.py"
    script.write_text(oauth_loopback.build_script(authorization, return_url))

    def browser_requests():
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as browser:
            assert browser.get(callback, params={"state": "wrong", **answer}).status_code == 400
            assert browser.get(callback, params={"state": "é", **answer}).status_code == 400
            assert browser.get(callback, params={"state": state, **answer}, headers={"Host": "attacker.example"}).status_code == 400
            assert browser.get(callback, params=[("state", state), ("state", state), *answer.items()]).status_code == 400
            assert browser.get(callback + "/other", params={"state": state, **answer}).status_code == 400
            response = browser.get(callback, params={"state": state, **answer, "iss": "https://oauth.example.test", "extra": "discarded"})
            assert response.status_code == 302
            location = urlsplit(response.headers["Location"])
            assert location.scheme + "://" + location.netloc + location.path == return_url
            assert parse_qs(location.query) == {"state": [state], **{key: [value] for key, value in answer.items()}, "iss": ["https://oauth.example.test"]}
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["Referrer-Policy"] == "no-referrer"

    with ThreadPoolExecutor(max_workers=1) as pool:
        requests = []

        def open_browser(url):
            assert url == authorization
            requests.append(pool.submit(browser_requests))
            return True

        monkeypatch.setattr(oauth_loopback.webbrowser, "open", open_browser)
        downloaded = runpy.run_path(str(script))
        assert downloaded["connect"](authorization, return_url, timeout_seconds=5)
        requests[0].result(timeout=10)
    output = capsys.readouterr()
    assert "synthetic-private-code" not in output.out + output.err
    with socket.socket() as released:
        assert released.connect_ex(("127.0.0.1", port)) != 0


def test_relay_port_conflict_does_not_open_browser_and_timeout_releases_port(monkeypatch):
    opened = []
    monkeypatch.setattr(oauth_loopback.webbrowser, "open", lambda url: opened.append(url) or True)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        authorization = "https://oauth.example.test/authorize?" + urlencode({
            "redirect_uri": f"http://127.0.0.1:{port}/oauth/callback", "state": "synthetic-state-0000001"})
        assert not oauth_loopback.connect(authorization, "https://private.example.test/connection/oauth-callback")
        assert not opened
    assert not oauth_loopback.connect(authorization, "https://private.example.test/connection/oauth-callback", timeout_seconds=0)
    assert opened == [authorization]
    with socket.socket() as released:
        released.bind(("127.0.0.1", port))
