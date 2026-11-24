# 0323 — Desktop MCP relay over outbound HTTPS

Status: accepted for implementation.

The desktop main process discovers MCP configurations and enables them individually
for the selected origin. Sharing creates a normal Streamable HTTP Service through
a web session with Service edit rights. Agent connections and function permissions
remain in the existing Services domain. Remote tabs receive no local IPC access.

The desktop polls and submits replies using outbound HTTPS requests on the
existing Galaris origin. The standard MCP client reaches the authenticated relay
on the backend's existing HTTP listener. Separate per-Service credentials authorize
the desktop and MCP sides. This approach works with ordinary HTTP reverse proxies
and avoids requiring an upgrade to a different network protocol or a public desktop
address.

PostgreSQL holds short-lived encrypted messages so different backend workers can
consume and complete requests. A claim is never replayed after network loss.
Revoking a Service removes its relay credential and pending messages. A disabled
or disconnected device retains its Service configuration and rejects new calls
after the presence window expires. The desktop runs only configurations approved
locally for the selected origin. Function permissions remain in Galaris. The relay
rejects direct resource reads using the `file:` scheme. Local MCP implementations
retain their own operating system permissions.
