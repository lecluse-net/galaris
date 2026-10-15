"""One-shot, standard-library-only OAuth relay for the browser's workstation.

This module is also downloaded as a standalone script. Keep it independent from
Galaris imports: it receives only a public authorization URL and a return URL,
never a PKCE verifier, access token, refresh token or Galaris session.
"""

from __future__ import annotations

import secrets
import socket
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit


REDIRECT_URI = "http://127.0.0.1:3334/oauth/callback"


def build_script(authorization_url: str, return_url: str) -> str:
    source = Path(__file__).read_text(encoding="utf-8")
    # repr produces string literals, never executable URL fragments.
    return source + f"\nif __name__ == '__main__':\n    sys.exit(0 if connect({authorization_url!r}, {return_url!r}) else 1)\n"


def connect(authorization_url: str, return_url: str, *, timeout_seconds: float = 600) -> bool:
    authorization = urlsplit(authorization_url)
    parameters = parse_qs(authorization.query)
    callback = urlsplit(parameters["redirect_uri"][0])
    state = parameters["state"][0]
    destination = urlsplit(return_url)
    if (authorization.scheme != "https" or authorization.username or authorization.password
            or callback.scheme != "http" or callback.hostname != "127.0.0.1" or not callback.port
            or callback.path != "/oauth/callback" or callback.query or callback.fragment
            or callback.username or callback.password
            or destination.query or destination.fragment or destination.username or destination.password
            or not destination.hostname
            or (destination.scheme != "https" and not (destination.scheme == "http"
                and destination.hostname in {"localhost", "127.0.0.1", "::1"}))):
        raise ValueError("Invalid OAuth relay configuration")
    completed = False

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            # The URL contains an authorization code. Never log requests.
            pass

        def do_GET(self) -> None:
            nonlocal completed
            parts = urlsplit(self.path)
            query = parse_qs(parts.query, keep_blank_values=True)
            allowed = {"state", "code", "error", "iss"}
            valid = (len(self.path) <= 20000 and self.headers.get("Host") == callback.netloc
                     and parts.path == callback.path and not parts.scheme and not parts.netloc
                     and all(len(values) == 1 for key, values in query.items() if key in allowed)
                     and secrets.compare_digest(query.get("state", [""])[0].encode(), state.encode())
                     and bool(query.get("code", [""])[0] or query.get("error", [""])[0]))
            if not valid:
                self.send_error(400)
                return
            location = return_url + "?" + urlencode({key: query[key][0] for key in allowed if key in query})
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self.end_headers()
            completed = True

    class CallbackServer(HTTPServer):
        def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address

    try:
        with CallbackServer(("127.0.0.1", callback.port), CallbackHandler) as server:
            server.timeout = 1
            deadline = time.monotonic() + timeout_seconds
            sys.stderr.write("Opening your browser to connect the account. This relay closes after the callback or after 10 minutes.\n")
            if not webbrowser.open(authorization_url):
                sys.stderr.write("Open the authorization link shown in Galaris in this computer's browser.\n")
            while not completed and time.monotonic() < deadline:
                server.handle_request()
    except OSError:
        sys.stderr.write("Cannot open the local callback port. Close any other account connection relay and retry.\n")
        return False
    return completed
