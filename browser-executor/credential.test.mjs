import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { provisionCredential, readCredential } from './credential.mjs';

test('shared credential is generated independently of obsolete environment values', t => {
  const root = mkdtempSync(join(tmpdir(), 'galaris-credential-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, 'token');
  const previous = process.env.BROWSER_EXECUTOR_TOKEN;
  t.after(() => {
    if (previous === undefined) delete process.env.BROWSER_EXECUTOR_TOKEN;
    else process.env.BROWSER_EXECUTOR_TOKEN = previous;
  });
  process.env.BROWSER_EXECUTOR_TOKEN = 'obsolete-browser-secret-ignored-0001';
  provisionCredential(path);
  const first = readCredential(path);
  assert.notEqual(first, process.env.BROWSER_EXECUTOR_TOKEN);
  assert.equal(statSync(path).mode & 0o777, 0o440);
  provisionCredential(path);
  assert.equal(readCredential(path), first);
});

test('fresh credentials persist and corrupt files never silently rotate', t => {
  const root = mkdtempSync(join(tmpdir(), 'galaris-credential-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, 'token');
  provisionCredential(path);
  const first = readCredential(path);
  assert.equal(first.length, 64);
  provisionCredential(path);
  assert.equal(readCredential(path), first);
  const corrupt = join(root, 'corrupt');
  writeFileSync(corrupt, 'broken');
  assert.throws(() => provisionCredential(corrupt));
  assert.equal(readFileSync(corrupt, 'utf8'), 'broken');
  assert.throws(() => readCredential(join(root, 'missing')));
});
