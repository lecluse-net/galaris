// Run inside the isolated installation's browser executor, against its real UI/API.
import assert from 'node:assert/strict'
import { randomBytes } from 'node:crypto'
import { lookup } from 'node:dns/promises'
import { chromium } from 'playwright'

const baseURL = process.argv[2]
const email = 'installation-admin@example.com'
const password = randomBytes(24).toString('hex')
// Access the host-published port with the configured localhost origin, so the
// production Host/Origin checks remain enabled throughout the real browser flow.
const { address } = await lookup('host.docker.internal', { family: 4 })
const browser = await chromium.launch({ headless: true, args: [`--host-resolver-rules=MAP localhost ${address}`] })
try {
  const context = await browser.newContext({ baseURL, locale: 'en-US' })
  const page = await context.newPage()
  await page.goto('/')
  await page.locator('a[href="/user/register"]').click()
  await page.waitForURL('**/user/register')
  await page.locator('input[type="email"]').fill(email)
  await page.locator('input[type="password"]').nth(0).fill(password)
  await page.locator('input[type="password"]').nth(1).fill(password)
  const registered = page.waitForResponse(response => response.url().endsWith('/api/auth/register'))
  const loggedIn = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('form button[type="submit"]').click()
  assert.equal((await registered).status(), 201)
  const session = await loggedIn
  assert.equal(session.status(), 200)
  const { access_token } = await session.json()
  const claims = JSON.parse(Buffer.from(access_token.split('.')[1], 'base64url').toString())
  assert.equal(claims.role_code, 'admin')
  await page.waitForURL(baseURL + '/')
  const status = await page.evaluate(async () => (await fetch('/api/auth/registration-status')).json())
  assert.deepEqual(status, { registration_open: false, initial_admin_required: false })
  await context.close()

  const returningContext = await browser.newContext({ baseURL, locale: 'en-US' })
  const returning = await returningContext.newPage()
  await returning.goto('/')
  await returning.locator('a[href="/user/login"]').click()
  await returning.waitForURL('**/user/login')
  await returning.locator('input[type="email"]').fill(email)
  await returning.locator('input[type="password"]').fill(password)
  const relogin = returning.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await returning.locator('form button[type="submit"]').click()
  assert.equal((await relogin).status(), 200)
  await returning.waitForURL(baseURL + '/')
  await returningContext.close()
  console.log('PASS: first administrator created through the login button, authenticated, and able to log in again.')
} finally {
  await browser.close()
}
