// Real browser, real Chat REST and runtime. No route interception or model double.
import { chromium, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'

const directory = '/artifacts'
const manifest = JSON.parse(await readFile(`${directory}/manifest.json`, 'utf8'))
const session = JSON.parse(await readFile(`${directory}/_session.json`, 'utf8'))
const stage = process.argv[2] ?? 'check'
if (!['check', 'submit', 'capture'].includes(stage)) throw new Error('Unknown pilot browser stage')
if (stage === 'submit' && !manifest.executable) throw new Error('Prepared-only pilot cannot call a model')
const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: 'block' })
const page = await context.newPage()
const errors = []
const expectedResponses = []
let subscribed = false
page.on('pageerror', error => errors.push({ type: 'pageerror', message: error.message }))
page.on('requestfailed', request => {
  if (request.failure()?.errorText === 'net::ERR_ABORTED') return // Our full-page navigation cancels pending reads.
  errors.push({ type: 'requestfailed', url: new URL(request.url()).pathname, message: request.failure()?.errorText })
})
page.on('response', response => {
  const path = new URL(response.url()).pathname
  // Missing optional avatars use the product's ordinary initial-letter fallback.
  if (response.status() === 404 && /^\/api\/chat\/agents\/\d+\/avatar$/.test(path)) {
    expectedResponses.push({ type: 'avatar-absent', url: path, status: 404 })
    return
  }
  if (response.status() >= 400 && !(path === '/api/auth/refresh' && response.status() === 401))
    errors.push({ type: 'http-error', url: path, status: response.status() })
})
// Socket.IO may initially use HTTP polling before upgrading to WebSocket.
// Record only the subscription fact, never the handshake's authentication data.
page.on('request', request => {
  if (new URL(request.url()).pathname.includes('socket.io')) {
    const body = request.postData() ?? ''
    if (body.includes('room.join') && body.includes(manifest.room_id)) subscribed = true
  }
})
page.on('websocket', socket => socket.on('framesent', ({ payload }) => {
  const frame = String(payload)
  if (frame.includes('room.join') && frame.includes(manifest.room_id)) subscribed = true
}))
try {
  const initialRefresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('http://localhost:8484/user/login')
  await initialRefresh
  await page.locator('input[type=email]').fill(session.email)
  await page.locator('input[type=password]').fill(session.password)
  await page.locator('button[type=submit]').click()
  await page.locator('input[type=password]').waitFor({ state: 'detached' })
  const restored = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto(`http://localhost:8484/chat?room=${manifest.room_id}`)
  await restored
  const composer = page.locator('.composer-fields textarea')
  await composer.waitFor()
  await expect.poll(() => subscribed, { timeout: 20000, message: 'Chat must subscribe to the pilot room' }).toBe(true)
  if (stage === 'check' || stage === 'submit')
    await page.locator('.conversation-empty-state').waitFor()
  else
    await page.locator('.message-row').first().waitFor()
  if (stage === 'submit') {
    // @task is the product's existing explicit Task directive.
    await composer.fill(`@task ${manifest.mission}`)
    const sent = page.waitForResponse(res => res.url().endsWith(`/rooms/${manifest.room_id}/messages`) && res.request().method() === 'POST')
    await page.locator('.composer-send-button').click()
    const accepted = await sent
    if (!accepted.ok()) throw new Error(`Chat submission failed: ${accepted.status()}`)
    await writeFile(`${directory}/submission.json`, JSON.stringify({ channel: 'browser', message: await accepted.json() }, null, 2), { mode: 0o600 })
    await expect(page.locator('.message-timeline')).toContainText('Prépare une synthèse décisionnelle')
  }
  await page.screenshot({ path: `${directory}/browser-${stage}.png`, fullPage: true })
  await writeFile(`${directory}/browser-${stage}-state.json`, JSON.stringify({ room_subscription_sent: subscribed,
    secure_context: await page.evaluate(() => window.isSecureContext), expected_responses: expectedResponses }, null, 2), { mode: 0o600 })
  if (errors.length) throw new Error('Browser errors were observed; inspect the browser errors artifact')
} catch (error) {
  await page.screenshot({ path: `${directory}/browser-${stage}-failure.png`, fullPage: true }).catch(() => {})
  // Playwright locator errors can contain input values, including the synthetic password.
  const message = String(error?.message ?? error).replaceAll(session.password, '[redacted]')
  errors.push({ type: 'pilot-error', message })
  throw new Error(message)
} finally {
  await writeFile(`${directory}/browser-${stage}-errors.json`, JSON.stringify(errors, null, 2), { mode: 0o600 })
  await context.close()
  await browser.close()
}
