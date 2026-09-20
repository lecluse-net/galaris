import assert from "node:assert/strict";
import test from "node:test";
import { SessionPool } from "./sessions.mjs";

function gate() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}
function session(id = "one") {
  return { id, touchedAt: 0, idleTtlMs: 500, context: { close: async () => {} } };
}

test("pending creations reserve capacity and release it on failure", async () => {
  const pool = new SessionPool(1);
  const ready = gate();
  const first = pool.create(async () => { await ready.promise; throw Error("creation failed"); }, () => {});
  await assert.rejects(pool.create(() => session(), () => {}), { code: "capacity_reached" });
  ready.resolve();
  await assert.rejects(first, /creation failed/);
  assert.equal(await pool.create(() => session(), () => "ready"), "ready");
});

test("failed initialization closes context and returns capacity", async () => {
  const pool = new SessionPool(1);
  let closed = 0;
  const item = session();
  item.context.close = async () => { closed += 1; };
  await assert.rejects(pool.create(() => item, () => { throw Error("navigation failed"); }), /navigation failed/);
  assert.equal(closed, 1);
  assert.equal(pool.size, 0);
  await pool.create(() => session(), () => {});
});

test("admission uses current capacity without evicting sessions and expiry uses each session's idle timeout", async () => {
  const pool = new SessionPool(1);
  const first = session("one");
  const second = { ...session("two"), idleTtlMs: 10_000 };
  await pool.create(() => first, () => {}, 1);
  await pool.create(() => second, () => {}, 2);
  await assert.rejects(pool.create(() => session("three"), () => {}, 1), { code: "capacity_reached" });
  assert.equal(pool.size, 2);
  await pool.sweep(Date.now() + 1_000);
  assert.equal(pool.has(first.id), false);
  assert.equal(pool.has(second.id), true);
  second.idleTtlMs = 500;
  await pool.sweep(Date.now() + 1_000);
  assert.equal(pool.size, 0);
});

test("actions serialize, failures release queue, expiry never closes busy sessions", async () => {
  const pool = new SessionPool(1);
  const item = session();
  await pool.create(() => item, () => {});
  const ready = gate();
  const calls = [];
  const first = pool.run(item, async () => { calls.push("first"); await ready.promise; throw Error("failed"); });
  const second = pool.run(item, async () => { calls.push("second"); });
  await pool.sweep(Date.now() + 1000);
  assert.equal(pool.size, 1);
  assert.deepEqual(calls, ["first"]);
  ready.resolve();
  await assert.rejects(first, /failed/);
  await second;
  assert.deepEqual(calls, ["first", "second"]);
  await pool.sweep(Date.now() + 1000);
  assert.equal(pool.size, 0);
});

test("close waits for accepted actions, rejects new actions and holds capacity until cleanup", async () => {
  const pool = new SessionPool(1);
  const item = session();
  const action = gate();
  const cleanup = gate();
  item.context.close = () => cleanup.promise;
  await pool.create(() => item, () => {});
  const running = pool.run(item, () => action.promise);
  const closed = pool.close(item.id);
  await assert.rejects(pool.run(item, () => {}), { code: "session_not_found" });
  await assert.rejects(pool.create(() => session("two"), () => {}), { code: "capacity_reached" });
  action.resolve();
  await running;
  assert.equal(pool.size, 1);
  cleanup.resolve();
  await closed;
  await pool.create(() => session("two"), () => {});
});
