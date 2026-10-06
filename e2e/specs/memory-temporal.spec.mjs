import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test.use({ timezoneId: 'Pacific/Honolulu' })

for (const width of [1440, 390]) test(`memory dates use the global timezone through the real API at ${width}px`, async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const errors = collectPageErrors(page)
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok(), await seeded.text()).toBeTruthy()
  const fixture = await seeded.json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const defaults = await (await request.get('/api/memory/temporal/defaults', { headers })).json()
  expect(defaults.timezone).not.toBe('Pacific/Honolulu')
  const created = await request.post('/api/memory/items', { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic global calendar appointment',
    media_type: 'text/html',
    payload: { text: '<p>Preserved appointment evidence.</p>' },
    temporal: { year: 2027, month: 9, day: 27, hour: 9, minute: 30 },
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const item = await created.json()
  expect(item.temporal).not.toHaveProperty('timezone')
  await errors.settle()
  const initialBrowse = page.waitForResponse(response => response.url().endsWith('/api/memory/browse'))
  await page.goto(`/memory?agent=${fixture.agent_id}`)
  await initialBrowse
  if (width < 1024) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop => backdrop.click({ position: { x: 380, y: 150 } }), { times: 1 })
  const target = page.getByLabel('Date et heure cibles', { exact: true })
  await expect(target).toBeEnabled()
  await target.fill('2027-09-27T09:30')
  const searched = page.waitForResponse(response => response.url().endsWith('/api/memory/browse'))
  await target.press('Enter')
  const response = await searched
  expect(response.ok(), await response.text()).toBeTruthy()
  expect(response.request().postDataJSON().temporal).toEqual({ target_at: '2027-09-27T09:30', lookahead_hours: 0 })
  const pageData = await response.json()
  expect(pageData.temporal_window.timezone).toBe(defaults.timezone)
  const hit = pageData.hits.find(hit => hit.item.id === item.id)
  expect(hit).toBeTruthy()
  const expectedMatch = await page.evaluate(({ at, zone }) => new Intl.DateTimeFormat('fr', {
    timeZone: zone, dateStyle: 'medium', timeStyle: 'short',
  }).format(new Date(at)), { at: hit.temporal_match_at, zone: defaults.timezone })
  await expect(page.getByText(/Correspondance :/)).toContainText(expectedMatch)
  await page.getByText(item.title, { exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Heure', { exact: true })).toHaveValue('9')
  await expect(dialog.getByLabel('Minute', { exact: true })).toHaveValue('30')
  await expect(dialog.getByLabel('Fuseau horaire', { exact: true })).toHaveCount(0)
  await expect(dialog.getByText('Preserved appointment evidence.', { exact: true })).toBeVisible()
  await dialog.getByLabel('Heure', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('memory-global-timezone.png') })
  await dialog.getByRole('button', { name: 'Fermer', exact: true }).click()
  await expect(dialog).toBeHidden()
  await page.getByText(item.title, { exact: true }).click()
  await expect(dialog.getByLabel('Heure', { exact: true })).toHaveValue('9')
  await expect(target).toHaveValue('2027-09-27T09:30')
  await errors.settle()
  expect(errors()).toEqual([])
})
