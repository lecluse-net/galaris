// Per-context HTTP(S) filtering. HTTPS is decrypted only inside this process,
// then sent upstream with normal certificate/hostname verification and pinned DNS.
import http from 'node:http';
import https from 'node:https';
import tls from 'node:tls';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { BrowserRequestError, resolveTarget } from './lib.mjs';

let certificate;
function localCertificate() {
  certificate ??= (async () => {
    const directory = await mkdtemp(join(tmpdir(), 'browser-proxy-'));
    try {
      await promisify(execFile)('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', join(directory, 'key'), '-out', join(directory, 'cert'),
        '-days', '2', '-subj', '/CN=browser-filter.invalid'], { timeout: 10000 });
      return { key: await readFile(join(directory, 'key')), cert: await readFile(join(directory, 'cert')) };
    } finally { await rm(directory, { recursive: true, force: true }); }
  })();
  return certificate;
}

const stripHopHeaders = headers => {
  const result = { ...headers };
  for (const name of ['proxy-authorization', 'proxy-connection', 'connection', 'keep-alive', 'transfer-encoding']) delete result[name];
  return result;
};

export async function startNetworkProxy({ owner, token, authorizationUrl = 'http://backend:8000/api/browser/network/authorize' }) {
  const sockets = new Set();
  const issues = new Map();
  const secureContext = tls.createSecureContext(await localCertificate());
  let closed = false;
  async function authorize(raw, method, connectedTarget = null, bodySha256 = null) {
    if (closed) throw new BrowserRequestError('session_not_found', 'Session closed', 404);
    const target = connectedTarget ?? await resolveTarget(raw);
    let decision;
    try {
      const response = await fetch(authorizationUrl, {
        method: 'POST', headers: { 'content-type': 'application/json', 'x-galaris-browser-token': token },
        body: JSON.stringify({ owner, url: target.url.href, method, addresses: target.addresses,
          operation_key: randomUUID(), body_sha256: bodySha256,
          authorization_generation: connectedTarget?.authorizationGeneration ?? null }),
        signal: AbortSignal.timeout(15000), redirect: 'error',
      });
      if (!response.ok) throw new Error('Authorization unavailable');
      decision = await response.json();
      if (typeof decision?.allowed !== 'boolean') throw new Error('Invalid authorization response');
    } catch {
      if (issues.size < 32) issues.set(`${target.url.origin}:${method}`, {
        code: 'authorization_unavailable', origin: target.url.origin, method, permission_keys: [],
      });
      throw new BrowserRequestError('unavailable', 'Network authorization unavailable', 503);
    }
    if (decision.allowed !== true) {
      const issue = { code: String(decision.code || 'blocked_url'), origin: target.url.origin,
        method, permission_keys: Array.isArray(decision.permission_keys) ? decision.permission_keys : [] };
      if (issues.size < 32) issues.set(`${issue.origin}:${method}`, issue);
      throw new BrowserRequestError('blocked_url', 'Destination blocked by browser policy', 403);
    }
    if (closed) throw new BrowserRequestError('session_not_found', 'Session closed', 404);
    if (Number.isInteger(decision.authorization_generation)) target.authorizationGeneration = decision.authorization_generation;
    return target;
  }
  function track(socket) {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    socket.on('error', () => socket.destroy());
    return socket;
  }
  function targetUrl(request) {
    const origin = request.socket.browserOrigin;
    // A TLS tunnel cannot change its authority through a forged Host header.
    if (!origin) return request.url;
    const target = new URL(request.url, origin);
    if (target.origin !== origin) throw new BrowserRequestError('blocked_url', 'Tunnel authority mismatch', 403);
    return target.href;
  }
  async function forward(request, response) {
    try {
      const chunks = [];
      let size = 0;
      for await (const chunk of request) {
        size += chunk.length;
        if (size > 50 * 1024 * 1024) throw new BrowserRequestError('blocked_url', 'Request body exceeds the authorization limit', 413);
        chunks.push(chunk);
      }
      const body = Buffer.concat(chunks);
      const { url, address } = await authorize(targetUrl(request), request.method, null,
        createHash('sha256').update(body).digest('hex'));
      const secure = url.protocol === 'https:';
      const upstream = (secure ? https : http).request({
        host: address, port: url.port || (secure ? 443 : 80), servername: url.hostname.replace(/^\[|\]$/g, ''),
        method: request.method, path: `${url.pathname}${url.search}`,
        headers: { ...stripHopHeaders(request.headers), host: url.host },
        agent: false, timeout: 30000,
      }, remote => {
        response.writeHead(remote.statusCode || 502, stripHopHeaders(remote.headers));
        remote.on('error', () => response.destroy());
        remote.pipe(response);
      });
      upstream.on('socket', track);
      upstream.on('timeout', () => upstream.destroy());
      upstream.on('error', () => { if (!response.headersSent) response.writeHead(502); response.end(); });
      request.on('error', () => upstream.destroy());
      response.on('close', () => upstream.destroy());
      upstream.end(body);
    } catch {
      response.writeHead(403, { connection: 'close', 'content-type': 'text/plain' });
      response.end('Blocked by browser network policy');
    }
  }
  async function upgrade(request, socket, head) {
    try {
      const raw = targetUrl(request).replace(/^ws:/, 'http:').replace(/^wss:/, 'https:');
      const target = await authorize(raw, 'WEBSOCKET');
      const { url, address } = target;
      const secure = url.protocol === 'https:';
      const upstream = (secure ? https : http).request({
        host: address, port: url.port || (secure ? 443 : 80), servername: url.hostname.replace(/^\[|\]$/g, ''),
        path: `${url.pathname}${url.search}`, agent: false, timeout: 30000,
        headers: { ...stripHopHeaders(request.headers), host: url.host, connection: 'Upgrade' },
      });
      upstream.on('socket', track);
      upstream.on('upgrade', (response, remote, remoteHead) => {
        socket.write(`HTTP/1.1 101 Switching Protocols\r\n${Object.entries(response.headers).map(([key, value]) => `${key}: ${value}`).join('\r\n')}\r\n\r\n`);
        if (head.length) remote.write(head);
        if (remoteHead.length) socket.write(remoteHead);
        remote.pipe(socket); socket.pipe(remote);
        // Recheck established channels so revocation/configuration changes stop traffic.
        let checking = false;
        const interval = setInterval(() => {
          if (checking) return;
          checking = true;
          // An established connection keeps its actual destination even if DNS
          // changes later; a fresh lookup must not reclassify that socket.
          void authorize(raw, 'WEBSOCKET', target).catch(() => socket.destroy()).finally(() => { checking = false; });
        }, 1000);
        interval.unref();
        socket.on('close', () => { clearInterval(interval); remote.destroy(); });
      });
      upstream.on('response', () => socket.destroy());
      upstream.on('error', () => socket.destroy());
      upstream.on('timeout', () => upstream.destroy());
      upstream.end();
    } catch { socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'); }
  }
  const server = http.createServer((request, response) => { void forward(request, response); });
  const decrypted = http.createServer((request, response) => { void forward(request, response); });
  for (const listener of [server, decrypted]) {
    listener.on('connection', track);
    listener.on('upgrade', (request, socket, head) => { void upgrade(request, socket, head); });
    listener.on('clientError', (_error, socket) => socket.destroy());
  }
  server.on('connect', (request, socket, head) => {
    try {
      const authority = new URL(`https://${request.url}`);
      socket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      const start = data => {
        socket.pause(); socket.unshift(data);
        if (data[0] === 22) {
          const encrypted = track(new tls.TLSSocket(socket, { isServer: true, secureContext }));
          encrypted.browserOrigin = authority.origin;
          decrypted.emit('connection', encrypted);
        } else {
          // Chromium also uses CONNECT for unencrypted ws:// channels. Parse
          // their HTTP handshake here; never expose a blind TCP tunnel.
          socket.browserOrigin = new URL(`http://${request.url}`).origin;
          decrypted.emit('connection', socket);
          socket.resume();
        }
      };
      if (head.length) start(head); else socket.once('data', start);
    } catch { socket.destroy(); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  return {
    server: `http://127.0.0.1:${server.address().port}`,
    issues: () => [...issues.values()],
    clearIssues: () => issues.clear(),
    close() { closed = true; for (const socket of sockets) socket.destroy(); server.close(); },
  };
}
