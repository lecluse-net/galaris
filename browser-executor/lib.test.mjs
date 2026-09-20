import test from "node:test";
import assert from "node:assert/strict";

import {
  assertHttpUrl,
  parseOptionalBoundedInt,
  parseUrl,
  resolveTarget,
  screenshotCaptureWidth,
  screenshotSlices,
  safeReference,
} from "./lib.mjs";

test("accepts local HTTP(S) URLs and blocks credentialed or non-Web URLs", () => {
  assert.equal(parseUrl("http://localhost:5173/preview").hostname, "localhost");
  assert.equal(parseUrl("http://tool.internal/preview").hostname, "tool.internal");
  assert.equal(parseUrl("http://192.168.1.42/preview").hostname, "192.168.1.42");
  assert.throws(() => parseUrl("https://user:pass@example.com"));
  assert.throws(() => parseUrl("file:///etc/passwd"));
});

test("resolves public, private, link-local, and loopback IP literals", async () => {
  for (const raw of [
    "https://8.8.8.8/",
    "http://127.0.0.1:5173/",
    "http://169.254.1.1/",
    "http://10.1.2.3/",
    "http://[::1]:3000/",
  ]) {
    const target = await resolveTarget(raw);
    assert.equal(target.url.href, raw);
    assert.ok(target.address.length > 0);
  }
});

test("resolves localhost as an allowed destination", async () => {
  const target = await resolveTarget("http://localhost:5173/preview");
  assert.equal(target.url.hostname, "localhost");
  assert.equal(target.address, "127.0.0.1");
  assert.equal(
    (await assertHttpUrl("http://localhost:5173/preview")).hostname,
    "localhost",
  );
});

test("tiles and truncates a tall page", () => {
  assert.deepEqual(screenshotSlices(7_500, 3_000, 2), {
    slices: [
      { index: 0, y: 0, height: 3_000 },
      { index: 1, y: 3_000, height: 3_000 },
    ],
    capturedHeight: 6_000,
    truncated: true,
  });
});

test("captures the selected responsive viewport width", () => {
  assert.equal(screenshotCaptureWidth(1_920, 1_920), 1_920);
  assert.equal(screenshotCaptureWidth(1_200, 390), 390);
  assert.equal(screenshotCaptureWidth(1_920, 1_920, 320), 320);
});

test("accepts only generated aria references", () => {
  assert.equal(safeReference("e42"), "e42");
  assert.throws(() => safeReference("button"));
});

test("accepts only bounded optional viewport dimensions", () => {
  assert.equal(parseOptionalBoundedInt(null, 320, 3_840, "invalid_viewport"), null);
  assert.equal(parseOptionalBoundedInt(390, 320, 3_840, "invalid_viewport"), 390);
  assert.throws(
    () => parseOptionalBoundedInt(319, 320, 3_840, "invalid_viewport"),
    (error) => error.code === "invalid_viewport",
  );
  assert.throws(
    () => parseOptionalBoundedInt("390px", 320, 3_840, "invalid_viewport"),
    (error) => error.code === "invalid_viewport",
  );
});
