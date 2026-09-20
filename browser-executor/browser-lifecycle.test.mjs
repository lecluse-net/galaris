import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';
import { BrowserLifecycle } from './browser-lifecycle.mjs';

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function browser(close = async () => {}) {
  return Object.assign(new EventEmitter(), { async close() { await close(); this.emit('disconnected'); } });
}

test('no eager launch, concurrent first requests share one launch, busy sessions prevent sleep', async () => {
  let launches = 0, crashes = 0;
  const pending = deferred();
  const lifecycle = new BrowserLifecycle(() => { launches++; return pending.promise; }, () => crashes++);
  assert.equal(launches, 0);
  const first = lifecycle.get(), second = lifecycle.get();
  await lifecycle.closeIfIdle(false);
  const chrome = browser();
  pending.resolve(chrome);
  assert.equal(await first, chrome);
  assert.equal(await second, chrome);
  assert.equal(launches, 1);
  await lifecycle.closeIfIdle(true);
  assert.equal(await lifecycle.get(), chrome);
  await lifecycle.closeIfIdle(false);
  assert.equal(crashes, 0);
});

test('request arriving during idle close waits and launches a fresh browser', async () => {
  const closing = deferred();
  const old = browser(() => closing.promise), fresh = browser();
  let launches = 0;
  const lifecycle = new BrowserLifecycle(async () => ++launches === 1 ? old : fresh, () => assert.fail('intentional close is not a crash'));
  await lifecycle.get();
  const sleeping = lifecycle.closeIfIdle(false);
  const waking = lifecycle.get();
  assert.equal(launches, 1);
  closing.resolve();
  await sleeping;
  assert.equal(await waking, fresh);
  await lifecycle.stop();
});

test('failed launch can be retried and unexpected disconnection still triggers recovery', async () => {
  let launches = 0, crashes = 0;
  const chrome = browser();
  const lifecycle = new BrowserLifecycle(async () => {
    if (++launches === 1) throw new Error('launch failed');
    return chrome;
  }, () => crashes++);
  await assert.rejects(lifecycle.get(), /launch failed/);
  assert.equal(await lifecycle.get(), chrome);
  chrome.emit('disconnected');
  assert.equal(crashes, 1);
  await lifecycle.stop();
  assert.equal(crashes, 1);
});

test('shutdown during launch closes the new browser and refuses further requests', async () => {
  const pending = deferred();
  let closed = 0;
  const lifecycle = new BrowserLifecycle(() => pending.promise, () => assert.fail('shutdown is not a crash'));
  const launch = lifecycle.get();
  const rejected = assert.rejects(launch, /stopping/);
  const stopped = lifecycle.stop();
  pending.resolve(browser(async () => { closed++; }));
  await Promise.all([rejected, stopped]);
  assert.equal(closed, 1);
  await assert.rejects(lifecycle.get(), /stopping/);
});
