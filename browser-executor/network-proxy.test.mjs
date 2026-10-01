import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import https from 'node:https';
import tls from 'node:tls';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from 'playwright';
import { startNetworkProxy } from './network-proxy.mjs';

async function listen(server) {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return `http://127.0.0.1:${server.address().port}`;
}

test('real Chromium checks every request, redirect and WebSocket; revocation and backend failure close access', { timeout: 30000 }, async t => {
  const requests = [], checks = [], channels = new Set();
  let postAllowed = false, wsAllowed = false, available = true, blockedOrigin = '';
  const authorizer = http.createServer(async (req, res) => {
    assert.equal(req.headers['x-galaris-browser-token'], 'synthetic-token');
    let raw = ''; for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw); checks.push(body);
    const allowed = body.owner.agent_id === 7 && new URL(body.url).origin !== blockedOrigin &&
      (body.method === 'GET' || body.method === 'POST' && postAllowed || body.method === 'WEBSOCKET' && wsAllowed);
    res.writeHead(available ? 200 : 503, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ allowed, code: 'permission_required', permission_keys: ['synthetic'] }));
  });
  const authorizationUrl = await listen(authorizer);
  const blocked = http.createServer((req, res) => { requests.push('forbidden'); res.end('forbidden'); });
  blockedOrigin = await listen(blocked);
  const origin = http.createServer((req, res) => {
    requests.push(`${req.method} ${req.url}`);
    if (req.url === '/redirect') { res.writeHead(302, { location: blockedOrigin + '/landing' }); res.end(); return; }
    res.setHeader('content-type', 'text/html');
    res.end(req.url === '/' ? '<h1>Fixture</h1>' : 'accepted');
  });
  origin.on('upgrade', (req, socket) => {
    requests.push('WEBSOCKET'); channels.add(socket); socket.on('close', () => channels.delete(socket));
    const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
  });
  const base = await listen(origin);
  const proxy = await startNetworkProxy({ owner: { agent_id: 7 }, token: 'synthetic-token', authorizationUrl });
  const otherProxy = await startNetworkProxy({ owner: { agent_id: 8 }, token: 'synthetic-token', authorizationUrl });
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-quic', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'] });
  t.after(async () => {
    await browser.close(); proxy.close(); otherProxy.close();
    for (const socket of channels) socket.destroy();
    for (const server of [origin, blocked, authorizer]) { server.closeAllConnections(); server.close(); }
  });
  const context = await browser.newContext({ ignoreHTTPSErrors: true, proxy: { server: proxy.server, bypass: '<-loopback>' }, serviceWorkers: 'block' });
  const page = await context.newPage();
  await page.goto(base);
  assert.match(await page.textContent('body'), /Fixture/);
  const post = () => page.evaluate(async () => (await fetch('/save', { method: 'POST', body: 'fixture' })).status);
  assert.equal(await post(), 403);
  assert.ok(!requests.includes('POST /save'), 'denied body never reaches destination');
  postAllowed = true;
  assert.equal(await post(), 200);
  assert.equal(requests.filter(value => value === 'POST /save').length, 1);
  postAllowed = false;
  assert.equal(await post(), 403, 'existing contexts recheck saved grants');
  const other = await browser.newContext({ proxy: { server: otherProxy.server, bypass: '<-loopback>' } });
  const otherPage = await other.newPage();
  assert.equal((await otherPage.goto(base)).status(), 403, 'another owner cannot inherit the proxy grant');
  await page.goto(base + '/redirect');
  assert.ok(!requests.includes('forbidden'), 'redirect target is checked independently');
  await page.goto(base);
  await page.evaluate(url => new Promise(resolve => {
    const socket = new WebSocket(url); socket.onerror = () => resolve(); socket.onopen = () => resolve();
  }), base.replace('http:', 'ws:') + '/socket');
  assert.ok(!requests.includes('WEBSOCKET'), 'denied WebSocket never reaches destination');
  wsAllowed = true;
  await page.evaluate(url => new Promise((resolve, reject) => {
    window.fixtureSocket = new WebSocket(url);
    window.fixtureSocket.onopen = () => resolve(); window.fixtureSocket.onerror = () => reject(new Error('WebSocket denied'));
  }), base.replace('http:', 'ws:') + '/socket');
  wsAllowed = false;
  await page.waitForFunction(() => window.fixtureSocket.readyState === WebSocket.CLOSED);
  available = false;
  assert.equal(await post(), 403, 'unavailable authorization never opens access');
  assert.ok(proxy.issues().some(issue => issue.code === 'authorization_unavailable'));
  assert.ok(checks.some(check => new URL(check.url).pathname === '/save'), 'authorization receives the exact target path');
  assert.ok(checks.every(check => !('body' in check)), 'authorization receives a fingerprint rather than the raw body');
});

test('HTTPS POST is inspected, trusted destinations work and untrusted certificates remain rejected', { timeout: 15000 }, async t => {
  const directory = await mkdtemp(join(tmpdir(), 'network-fixture-'));
  await promisify(execFile)('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', join(directory, 'key'),
    '-out', join(directory, 'cert'), '-days', '1', '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1']);
  let hits = 0, allowed = true; const checks = [];
  const roots = tls.getCACertificates();
  const origin = https.createServer({ key: await readFile(join(directory, 'key')), cert: await readFile(join(directory, 'cert')) }, (_req, res) => { hits++; res.end('bad certificate accepted'); });
  const base = (await listen(origin)).replace('http:', 'https:');
  const auth = http.createServer(async (req, res) => {
    let raw = ''; for await (const chunk of req) raw += chunk;
    checks.push(JSON.parse(raw)); res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ allowed }));
  });
  const proxy = await startNetworkProxy({ owner: { agent_id: 7 }, token: 'synthetic', authorizationUrl: await listen(auth) });
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  t.after(async () => {
    await browser.close(); proxy.close();
    tls.setDefaultCACertificates(roots);
    for (const server of [origin, auth]) { server.closeAllConnections(); server.close(); }
    await rm(directory, { recursive: true, force: true });
  });
  const context = await browser.newContext({ ignoreHTTPSErrors: true, proxy: { server: proxy.server, bypass: '<-loopback>' } });
  const page = await context.newPage();
  await page.setContent(`<form action="${base}/save" method="post"><button>Submit</button></form>`);
  await Promise.all([page.waitForURL(base + '/save'), page.getByRole('button').click()]);
  assert.ok(checks.some(check => check.method === 'POST' && check.url === base + '/save' && /^[a-f0-9]{64}$/.test(check.body_sha256)), 'TLS preserves the exact target, method and body fingerprint for authorization');
  assert.equal(hits, 0, 'upstream TLS certificate verification remains enabled');
  tls.setDefaultCACertificates([...roots, await readFile(join(directory, 'cert'), 'utf8')]);
  const submit = async () => {
    await page.setContent(`<form action="${base}/save" method="post"><button>Submit</button></form>`);
    const [response] = await Promise.all([page.waitForResponse(base + '/save'), page.getByRole('button').click()]);
    return response.status();
  };
  assert.equal(await submit(), 200, 'trusted HTTPS remains usable');
  assert.equal(hits, 1);
  allowed = false;
  assert.equal(await submit(), 403);
  assert.equal(hits, 1, 'denied HTTPS POST never reaches the trusted destination');
});
