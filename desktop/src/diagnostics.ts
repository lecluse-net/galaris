import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from 'node:fs'
import path from 'node:path'

/** Update endpoints may contain signed redirects: retain the cause, never their secrets. */
function redact(value: string): string {
  return value.replace(/https?:\/\/[^\s"'<>]+/gi, input => {
    try { const url = new URL(input); return `${url.origin}${url.pathname}` } catch { return '[redacted-url]' }
  }).replace(/(bearer\s+)[^\s"',;]+/gi, '$1[redacted]')
    .replace(/((?:password|token|secret|authorization|api[_-]?key)["']?\s*[=:]\s*["']?)[^\s"',;}\]]+/gi, '$1[redacted]')
    .slice(0, 16_384)
}

function failure(error: unknown, depth = 0): Record<string, unknown> {
  if (!(error instanceof Error)) return { message: redact(String(error)) }
  return {
    message: redact(error.message), stack: redact(error.stack ?? ''),
    code: 'code' in error ? redact(String(error.code)) : undefined,
    exitStatus: 'exitCode' in error ? redact(String(error.exitCode)) : undefined,
    cause: error.cause && depth < 2 ? failure(error.cause, depth + 1) : undefined
  }
}

/** Two bounded local files survive restart and do not depend on external telemetry. */
export function writeFailure(directory: string, version: string, stage: string, error: unknown): void {
  mkdirSync(directory, { recursive: true, mode: 0o700 })
  const target = path.join(directory, 'desktop-update.log')
  if (existsSync(target) && statSync(target).size > 512 * 1024) renameSync(target, `${target}.1`)
  const record = { time: new Date().toISOString(), operation: 'galaris-desktop', stage, version, status: 'failed', ...failure(error) }
  appendFileSync(target, `${JSON.stringify(record)}\n`, { mode: 0o600 })
}
