import { randomBytes } from 'node:crypto';
import { closeSync, linkSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync, fsyncSync } from 'node:fs';
import { dirname } from 'node:path';

export const TOKEN_PATH = process.env.BROWSER_EXECUTOR_TOKEN_FILE || '/run/galaris-browser/token';

function validate(value) {
  if (typeof value !== 'string' || value.trim().length < 32) {
    throw new Error('The shared browser credential is missing or invalid');
  }
  return value.trim();
}

export function readCredential(path = TOKEN_PATH) {
  return validate(readFileSync(path, 'utf8'));
}

export function provisionCredential(path = TOKEN_PATH) {
  try {
    readCredential(path);
    return;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  const value = randomBytes(32).toString('hex');
  mkdirSync(dirname(path), { recursive: true, mode: 0o755 });
  const temporary = `${path}.${randomBytes(12).toString('hex')}.tmp`;
  const fd = openSync(temporary, 'wx', 0o440);
  try {
    writeFileSync(fd, value, 'utf8');
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  try {
    // Publish a complete file exactly once, even across concurrent initializers.
    linkSync(temporary, path);
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    readCredential(path);
  } finally {
    unlinkSync(temporary);
  }
}
