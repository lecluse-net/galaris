import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { readdirSync, readFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'

const port = 32119
const child = spawn(process.execPath, ['/opt/galaris-browser/source/server.mjs'], {
  env: { ...process.env, PORT: String(port), BROWSER_EXECUTOR_TOKEN: 'audit-isolated-placeholder' },
  stdio: ['ignore', 'ignore', 'pipe'],
})
const exit = once(child, 'exit')
let errors = ''
child.stderr.on('data', chunk => { errors = (errors + chunk).slice(-2000) })
try {
  const deadline = Date.now() + 15000
  for (;;) {
    // Isolated loopback health probe; no credentials or application data leave the container.
    // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
    try { if ((await fetch(`http://127.0.0.1:${port}/health`)).ok) break } catch {}
    assert.equal(child.exitCode, null, errors)
    assert.ok(Date.now() < deadline, errors)
    await delay(30)
  }
  const children = readdirSync('/proc').filter(name => /^\d+$/.test(name)).filter(name => {
    try {
      const stat = readFileSync(`/proc/${name}/stat`, 'utf8').split(') ')[1].split(' ')
      const command = readFileSync(`/proc/${name}/cmdline`, 'utf8')
      return Number(stat[1]) === child.pid && /chrome|chromium|headless_shell/.test(command)
    } catch { return false }
  })
  assert.equal(children.length, 1)
  process.kill(Number(children[0]), 'SIGKILL')
  await delay(1000)
  // The same isolated loopback probe must fail after the child is killed.
  // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
  await assert.rejects(fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(1000) }))
  assert.equal(child.exitCode, null)
  console.log('CONFIRMED: Chromium crash closes HTTP listener but Node remains alive (proxy still open)')
} finally {
  child.kill('SIGTERM')
  const timer = setTimeout(() => child.kill('SIGKILL'), 3000)
  await exit
  clearTimeout(timer)
}
