import { randomUUID } from 'node:crypto'
import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const width of [1440, 390]) test(`a Contacts-only role creates and reopens contacts without Memory or Agent administration at ${width}px`, async ({ page, request }) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width, height: 900 })
  const checked = async response => {
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const fixture = await checked(await request.post('/api/__test/seed'))
  const adminSession = await checked(await request.post('/api/auth/login-json', {
    data: { email: fixture.email, password: fixture.password },
  }))
  const admin = { Authorization: `Bearer ${adminSession.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const suffix = randomUUID()
  const credentials = { email: `synthetic-contact-${suffix}@example.com`, password: 'Synthetic-contact-only-123' }
  const user = await checked(await request.post('/api/auth/users', { headers: admin,
    data: { ...credentials, language: 'en', display_name: 'Synthetic contact operator' } }))
  const role = await checked(await request.post('/api/authorize/roles', { headers: admin,
    data: { code: `synthetic-contact-${suffix}`, display_name: 'Synthetic Contacts only' } }))
  const catalogue = await checked(await request.get('/api/authorize/privileges', { headers: admin }))
  const privilege = catalogue.find(item => item.code === 'CONTACT_EDIT')
  expect(privilege).toBeTruthy()
  await checked(await request.post(`/api/authorize/roles/${role.id}/privileges`, { headers: admin,
    data: { privilege_ids: [privilege.id] } }))
  await checked(await request.post('/api/authorize/assignments', { headers: admin,
    data: { user_id: user.id, role_id: role.id, is_default: true } }))
  const owner = await checked(await request.get(`/api/agents/${fixture.agent_id}`, { headers: admin }))
  const agent = await checked(await request.post('/api/agents', { headers: admin, data: {
    user_id: user.id, title_id: owner.title_id, code: `contact-${suffix}`,
    first_name: 'Synthetic', last_name: 'Contact operator',
  } }))

  const errors = collectPageErrors(page)
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(credentials.email)
  await page.locator('input[type=password]').fill(credentials.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await checked(await login)
  const failures = []
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (path.startsWith('/api/') && response.status() >= 400 && path !== '/api/auth/refresh') {
      failures.push(`${response.status()} ${path}`)
    }
  })
  await errors.settle()
  await page.goto('/memory/contacts')
  if (width < 1024) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), async backdrop => {
    await backdrop.click({ position: { x: width - 10, y: 200 } })
  })
  await page.getByRole('button', { name: 'Add email contact', exact: true }).click()
  const dialog = page.getByRole('dialog')
  const name = `Synthetic correspondent ${width}`
  await dialog.getByLabel('Display name', { exact: true }).fill(name)
  await dialog.getByLabel('Email address', { exact: true }).fill(`correspondent-${width}@example.org`)
  const saved = page.waitForResponse(response => new URL(response.url()).pathname === '/api/contacts' && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Create contact', exact: true }).click()
  expect((await saved).status()).toBe(201)
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText(name, { exact: true })).toBeVisible()
  await errors.settle()
  await page.reload()
  await expect(page.getByText(name, { exact: true })).toBeVisible()
  const headers = { Authorization: `Bearer ${session.access_token}` }
  expect((await request.get('/api/memory/recent', { headers })).status()).toBe(403)
  expect((await request.get('/api/agents', { headers })).status()).toBe(403)
  expect((await request.get('/api/contacts', { headers, params: { agent_id: fixture.agent_id } })).status()).toBe(404)
  const own = await checked(await request.get('/api/contacts', { headers, params: { agent_id: agent.id } }))
  expect(own.items.some(item => item.display_name === name)).toBe(true)
  expect(failures).toEqual([])
  expect(errors()).toEqual([])
})
