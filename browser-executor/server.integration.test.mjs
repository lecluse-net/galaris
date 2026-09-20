import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import net from 'node:net';
import test from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { readdirSync, readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function credentialFile(t, token) {
  const root = mkdtempSync(join(tmpdir(), 'galaris-browser-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, 'token');
  writeFileSync(path, token);
  return path;
}

function chromiumChildren(pid) {
  return readdirSync('/proc').filter(name => /^\d+$/.test(name)).filter(name => {
    try {
      const stat = readFileSync(`/proc/${name}/stat`, 'utf8').split(') ')[1].split(' ');
      const command = readFileSync(`/proc/${name}/cmdline`, 'utf8');
      return Number(stat[1]) === pid && /chrome|chromium|headless_shell/.test(command);
    } catch { return false; }
  });
}

test('Chromium crash exits with failure and a fresh executor serves new sessions', { timeout: 30_000 }, async t => {
  const running = new Set();
  async function start() {
    const reservation = net.createServer().listen(0, '127.0.0.1');
    await once(reservation, 'listening');
    const port = reservation.address().port;
    await new Promise(resolve => reservation.close(resolve));
    const token = 'isolated-browser-recovery-token-0001';
    const child = spawn(process.execPath, [fileURLToPath(new URL('./server.mjs', import.meta.url))], {
      env: { ...process.env, PORT: String(port), BROWSER_EXECUTOR_TOKEN_FILE: credentialFile(t, token) },
      stdio: 'ignore',
    });
    const exited = once(child, 'exit');
    const entry = { child, exited };
    running.add(entry);
    const base = `http://127.0.0.1:${port}`;
    const deadline = Date.now() + 10_000;
    for (;;) {
      try { if ((await fetch(base + '/health')).ok) break; } catch {}
      assert.equal(child.exitCode, null);
      assert.ok(Date.now() < deadline, 'executor startup timeout');
      await delay(25);
    }
    return { ...entry, base, token };
  }
  try {
    const failed = await start();
    assert.equal(chromiumChildren(failed.child.pid).length, 0, 'health must not launch Chromium');
    const first = await fetch(failed.base + '/v1/render-html', {
      method: 'POST', headers: { 'content-type': 'application/json', 'x-galaris-browser-token': failed.token },
      body: JSON.stringify({ owner: { agent_id: 1 }, html_base64: Buffer.from('<h1>First request</h1>').toString('base64') }),
      signal: AbortSignal.timeout(10_000),
    });
    assert.equal(first.status, 200);
    const chrome = chromiumChildren(failed.child.pid);
    assert.equal(chrome.length, 1);
    process.kill(Number(chrome[0]), 'SIGKILL');
    const outcome = await Promise.race([failed.exited, delay(5000).then(() => 'timeout')]);
    assert.deepEqual(outcome, [1, null]);
    const healthy = await start();
    const response = await fetch(healthy.base + '/v1/render-html', {
      method: 'POST', headers: { 'content-type': 'application/json', 'x-galaris-browser-token': healthy.token },
      body: JSON.stringify({ owner: { agent_id: 1 }, html_base64: Buffer.from('<html><head><meta property="og:description" content="Site description"><meta property="og:site_name" content="Publisher"></head><body><h1>Recovered</h1></body></html>').toString('base64') }),
      signal: AbortSignal.timeout(10_000),
    });
    assert.equal(response.status, 200);
    const page = await response.json();
    assert.equal(page.description, 'Site description');
    assert.equal(page.site_name, 'Publisher');
    const post = (path, body) => fetch(healthy.base + path, {
      method: 'POST', headers: { 'content-type': 'application/json', 'x-galaris-browser-token': healthy.token },
      body: JSON.stringify(body), signal: AbortSignal.timeout(10_000),
    });
    const html = Buffer.from('<body style="margin:0;height:1600px"><p>' + 'Readable text '.repeat(300) + '</p></body>').toString('base64');
    const captures = await Promise.all([500, 1000].map(height => post('/v1/render-html', {
      owner: { agent_id: 1 }, html_base64: html,
      settings: { viewport_width: 800, screenshot_tile_height: height, screenshot_max_tiles: 1 },
    }).then(async response => {
      assert.equal(response.status, 200);
      return response.json();
    })));
    assert.deepEqual(captures.map(result => result.captured_height), [500, 1000], 'concurrent captures retain their own preferences');
    for (const limit of [1000, 2000]) {
      const response = await post('/v1/action', {
        owner: { agent_id: 1 }, session_id: captures[0].session_id,
        action: 'content', max_chars: 10000, settings: { content_max_chars: limit },
      });
      assert.equal(response.status, 200);
      assert.equal((await response.json()).content.length, limit, 'existing session uses the next operation limits');
    }
    const largeHtml = Buffer.from('<p>' + 'x'.repeat(15000) + '</p>').toString('base64');
    assert.equal((await post('/v1/render-html', { owner: { agent_id: 1 }, html_base64: largeHtml,
      settings: { html_max_bytes: 10000 } })).status, 413);
    assert.equal((await post('/v1/render-html', { owner: { agent_id: 1 }, html_base64: largeHtml,
      settings: { html_max_bytes: 20000, screenshot_max_tiles: 1 } })).status, 200);
    assert.equal((await post('/v1/render-html', { owner: { agent_id: 1 }, html_base64: html,
      settings: { html_max_bytes: 750001 } })).status, 400);
    const exported = await fetch(healthy.base + '/v1/render-pdf', {
      method: 'POST', headers: { 'content-type': 'application/json', 'x-galaris-browser-token': healthy.token },
      body: JSON.stringify({ html: '<h1>Downloaded document</h1>' }),
    });
    assert.equal(exported.status, 200);
    assert.equal(exported.headers.get('content-type'), 'application/pdf');
    assert.equal(Buffer.from(await exported.arrayBuffer()).subarray(0, 5).toString(), '%PDF-');
    const unauthorized = await fetch(healthy.base + '/v1/render-pdf', {
      method: 'POST', body: JSON.stringify({ html: '<p>Denied</p>' }),
    });
    assert.equal(unauthorized.status, 401);
  } finally {
    for (const { child, exited } of running) {
      if (child.exitCode !== null) continue;
      child.kill('SIGTERM');
      const watchdog = setTimeout(() => child.kill('SIGKILL'), 5000);
      await exited;
      clearTimeout(watchdog);
    }
  }
});

test('real HTTP server bounds sessions, sleeps after expiry, and wakes for a fresh session', { timeout: 40_000 }, async t => {
  const reservation = net.createServer();
  reservation.listen(0, '127.0.0.1');
  await once(reservation, 'listening');
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const token = 'isolated-browser-test-token-00000001';
  const child = spawn(process.execPath, [fileURLToPath(new URL('./server.mjs', import.meta.url))], {
    env: { ...process.env, PORT: String(port), BROWSER_EXECUTOR_TOKEN_FILE: credentialFile(t, token) },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  const exited = once(child, 'exit');
  let errors = '';
  child.stderr.on('data', chunk => { errors = (errors + chunk).slice(-2000); });
  const base = `http://127.0.0.1:${port}`;
  const post = (path, body) => fetch(base + path, {
    method: 'POST', headers: { 'content-type': 'application/json', 'x-galaris-browser-token': token },
    body: JSON.stringify({ ...body, settings: { session_ttl_seconds: 10, max_sessions: 1, ...body.settings } }), signal: AbortSignal.timeout(10_000),
  });
  try {
    const deadline = Date.now() + 15_000;
    while (true) {
      try { if ((await fetch(base + '/health')).ok) break; } catch {}
      assert.equal(child.exitCode, null, errors);
      assert.ok(Date.now() < deadline, `startup timed out: ${errors}`);
      await delay(50);
    }
    const body = { owner: { agent_id: 1 }, html_base64: Buffer.from('<h1>Session test</h1>').toString('base64') };
    const responses = await Promise.all([post('/v1/render-html', body), post('/v1/render-html', body)]);
    assert.deepEqual(responses.map(r => r.status).sort(), [200, 503]);
    const winner = await responses.find(r => r.status === 200).json();
    const rejected = await responses.find(r => r.status === 503).json();
    assert.equal(rejected.error.code, 'capacity_reached');
    const extraResponse = await post('/v1/render-html', { ...body, settings: { max_sessions: 2 } });
    assert.equal(extraResponse.status, 200, 'raising the preference applies without restarting');
    const extra = await extraResponse.json();
    assert.equal((await post('/v1/render-html', body)).status, 503, 'lowering capacity blocks new sessions');
    assert.equal((await post('/v1/action', { owner: body.owner, session_id: extra.session_id, action: 'content' })).status, 200, 'lowering capacity preserves existing sessions');
    assert.equal((await post('/v1/close', { owner: body.owner, session_id: extra.session_id })).status, 200);
    for (const settings of [{ max_sessions: 0 }, { max_sessions: 257 }, { session_ttl_seconds: 9 }, { session_ttl_seconds: 3601 }]) {
      assert.equal((await post('/v1/render-html', { ...body, settings })).status, 400);
    }
    const closed = await post('/v1/close', { owner: body.owner, session_id: winner.session_id });
    assert.equal(closed.status, 200);
    const humanBody = { ...body, owner: { user_id: 1 } };
    const humanResponse = await post('/v1/render-html', humanBody);
    assert.equal(humanResponse.status, 200);
    const human = await humanResponse.json();
    assert.equal((await post('/v1/close', { owner: body.owner, session_id: human.session_id })).status, 404, 'an Agent cannot claim a human session with the same numeric id');
    assert.equal((await post('/v1/close', { owner: humanBody.owner, session_id: human.session_id })).status, 200);
    assert.equal((await post('/v1/render-html', { ...body, owner: { agent_id: 1, user_id: 1 } })).status, 400);
    assert.equal((await post('/v1/render-html', body)).status, 200);
    const sleepDeadline = Date.now() + 25_000;
    while (chromiumChildren(child.pid).length) {
      assert.ok(Date.now() < sleepDeadline, 'Chromium must exit once its sessions expire');
      await delay(100);
    }
    assert.equal(child.exitCode, null, 'intentional sleep must not terminate the executor');
    assert.deepEqual(await (await fetch(base + '/health')).json(), { status: 'ok' });
    assert.equal((await post('/v1/render-html', body)).status, 200, 'first request after sleep must succeed');
    assert.equal(chromiumChildren(child.pid).length, 1);
  } finally {
    child.kill('SIGTERM');
    const watchdog = globalThis.setTimeout(() => child.kill('SIGKILL'), 5000);
    await exited;
    clearTimeout(watchdog);
  }
});
