"""Connection limits and remembered permissions for every browser request."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, Field

from app.connection import connection_service
from app.messenger import request_permission, get_permission_decision
from app.tools import tool_service
from core.i18n import current_language, render_prompt, t

from .schemas import BrowserOwner


class NetworkRequest(BaseModel):
    owner: BrowserOwner
    url: str = Field(min_length=1, max_length=4096)
    method: str = Field(min_length=1, max_length=20)
    addresses: list[str] = Field(min_length=1, max_length=64)
    operation_key: str = Field(default_factory=lambda: str(uuid4()), max_length=128)
    body_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    authorization_generation: int | None = Field(default=None, ge=0)


class NetworkDecision(BaseModel):
    allowed: bool
    code: str = "allowed"
    permission_keys: list[str] = Field(default_factory=list)
    authorization_generation: int | None = None
    decision_source: str | None = None


def canonical_origin(raw: str) -> tuple[str, str, int]:
    url = urlsplit(raw)
    if url.scheme not in {"http", "https", "ws", "wss"} or not url.hostname or url.username is not None or url.password is not None:
        raise ValueError("Invalid browser URL")
    host = url.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    try:
        host = ipaddress.ip_address(host).compressed
    except ValueError:
        if not re.fullmatch(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)*", host):
            raise ValueError("Invalid browser hostname") from None
    scheme = "https" if url.scheme in {"https", "wss"} else "http"
    port = url.port or (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid browser port")
    authority = f"[{host}]" if ":" in host else host
    return f"{scheme}://{authority}:{port}", host, port


def is_local(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def filter_matches(rule: str, host: str, port: int, addresses: list[str]) -> bool:
    """Exact domains, explicit wildcard subdomains, IPs and CIDRs; optional port."""
    target = rule.lower().strip()
    if target.startswith("["):
        match = re.fullmatch(r"\[([^]]+)\](?::([0-9]+))?", target)
        if match is None:
            raise ValueError("Invalid IPv6 filter")
        target, port_text = match.groups()
    elif target.count(":") == 1:
        target, port_text = target.rsplit(":", 1)
    else:
        port_text = None
    if port_text is not None and (not port_text.isdigit() or not 1 <= int(port_text) <= 65535):
        raise ValueError("Invalid filter port")
    matches_port = port_text is None or int(port_text) == port
    try:
        network = ipaddress.ip_network(target, strict=False)
    except ValueError:
        wildcard = target.startswith("*.")
        name = target[2:] if wildcard else target
        _, normalized, _ = canonical_origin(f"http://{name}")
        if "/" in name or "*" in name or ":" in name:
            raise ValueError("Invalid domain filter")
        return matches_port and (host.endswith("." + normalized) if wildcard else host == normalized)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if matches_port and ip in network:
            return True
    return False


async def authorize_network(request: NetworkRequest) -> NetworkDecision:
    origin, host, port = canonical_origin(request.url)
    local = any(is_local(address) for address in request.addresses)
    method = request.method.upper()
    if method not in {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"}:
        return NetworkDecision(allowed=False, code="blocked_method")
    params: dict[str, object] = {}
    if request.owner.agent_id is not None:
        found = False
        for connection in await connection_service.get_connections_by_agent(request.owner.agent_id):
            tool = await tool_service.get_tool_by_id(connection.tool_id)
            if tool is not None and tool.code == "browser":
                if not connection.active:
                    return NetworkDecision(allowed=False, code="connection_inactive")
                _, params = await connection_service.get_params_as_dict(connection, decrypt_passwords=False)
                found = True
                break
        if not found:
            return NetworkDecision(allowed=False, code="connection_inactive")
    allow_local = str(params.get("allow_local_network", "false")).lower()
    mode = str(params.get("network_filter_mode", "block"))
    if allow_local not in {"true", "false"} or mode not in {"allow", "block"}:
        raise ValueError("Invalid network policy")
    if local and allow_local != "true":
        return NetworkDecision(allowed=False, code="local_network_blocked")
    raw_filter = str(params.get("network_filter") or "")
    rules = [rule for rule in re.split(r"[,\s]+", raw_filter) if rule]
    if len(raw_filter) > 16384 or len(rules) > 128:
        raise ValueError("Network filter too large")
    matches = [[filter_matches(rule, host, port, [address]) for rule in rules]
               for address in request.addresses]
    if (mode == "block" and any(any(row) for row in matches)) or (mode == "allow" and not all(any(row) for row in matches)):
        return NetworkDecision(allowed=False, code="destination_blocked")
    ask_methods = str(params.get("permission_methods") or "POST PUT PATCH DELETE WEBSOCKET").upper()
    methods = set(filter(None, re.split(r"[,\s]+", ask_methods)))
    if not methods <= {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"}:
        raise ValueError("Invalid permission methods")
    required: list[str] = []
    if local:
        required.append("local")
    if method in methods:
        required.append(method.lower())
    if request.owner.agent_id is None:
        return NetworkDecision(allowed=not required, code="blocked_url" if required else "allowed")
    decisions: list[bool | None] = []
    keys: list[str] = []
    from app.tools.facade import agent_authorization_policy as authorization_policy
    policy = await authorization_policy(request.owner.agent_id)
    all_sites_key = "browser:v1:all-sites"
    all_sites = await get_permission_decision(request.owner.agent_id, all_sites_key) if required else None
    # Existing per-site consent keeps its original scope.
    site_key = f"browser:v1:site:{origin}"
    site = await get_permission_decision(request.owner.agent_id, site_key) if required and not (all_sites and all_sites.allowed) else None
    automatic = False
    for action in required:
        key = f"browser:v1:{action}:{origin}"
        recorded = await get_permission_decision(request.owner.agent_id, key)
        if recorded is not None and recorded.allowed is False:
            decisions.append(False)
        elif action != "local" and ((all_sites is not None and all_sites.allowed is True)
                                   or (site is not None and site.allowed is True)):
            decisions.append(True)
        elif recorded is None and policy.yolo:
            automatic = True
            decisions.append(True)
        elif recorded is not None and recorded.allowed is True:
            decisions.append(True)
        else:
            language = await current_language(user_id=policy.manager_user_id)
            question = render_prompt(t("browser.permission_question", language), action=action, origin=origin)
            decision = await request_permission(
                request.owner.agent_id, key, question,
                always_key=all_sites_key if action != "local" else None,
                always_question=t("browser.all_sites_permission_question", language)
                if action != "local" else None,
            )
            decisions.append(decision.allowed)
        keys.append(key)
    if any(decision is False for decision in decisions):
        return NetworkDecision(allowed=False, code="permission_denied", permission_keys=keys)
    if any(decision is None for decision in decisions):
        return NetworkDecision(allowed=False, code="permission_required", permission_keys=keys)
    if automatic:
        if request.authorization_generation is not None and request.authorization_generation != policy.version:
            return NetworkDecision(allowed=False, code="authorization_invalidated", permission_keys=keys)
        from app.tools.facade import AuthorizationAction, claim_action, finish_action
        identifier = await claim_action(AuthorizationAction(
            agent_id=request.owner.agent_id, runtime="browser", context_key=f"task:{request.owner.task_id}" if request.owner.task_id else "principal:browser:taskless",
            callback_key=request.operation_key, source="domain", name="browser_network",
            arguments={"url": request.url, "method": method, "addresses": request.addresses, "body_sha256": request.body_sha256},
            configuration={"network_policy": params, "generation": policy.version}, preview=f"Browser: {method} {origin}",
        ))
        await finish_action(identifier, receipt={"network_permit": True, "generation": policy.version})
        return NetworkDecision(allowed=True, authorization_generation=policy.version, decision_source="agent_yolo")
    return NetworkDecision(allowed=True)
