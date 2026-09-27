import { test, expect } from '@playwright/test'

test('an occupied agent code is explained and becomes reusable after archival', async ({ page, request }) => {
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok()).toBeTruthy()
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
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const original = await (await request.get(`/api/agents/${fixture.agent_id}`, { headers })).json()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    const expectedConflict = path === '/api/agents' && response.status() === 400
    if (path.startsWith('/api/') && response.status() >= 400 && !expectedConflict) {
      errors.push(`${response.status()} ${response.request().method()} ${path}`)
    }
  })
  await page.goto('/agent')
  await page.getByRole('button', { name: 'Nouvel Agent', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel("Code de l'agent", { exact: true }).fill(original.code)
  await dialog.getByLabel('Civilité *', { exact: true }).click()
  await page.getByRole('option', { name: `${original.title.label} (M)`, exact: true }).click()
  await dialog.getByLabel('Prénom *', { exact: true }).fill('Remplaçant')
  await dialog.getByRole('button', { name: 'Créer', exact: true }).click()
  await expect(page.getByText('Ce code est déjà utilisé par un autre agent. Veuillez choisir un autre code.', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('Prénom *', { exact: true })).toHaveValue('Remplaçant')

  const archived = await request.delete(`/api/agents/${fixture.agent_id}`, { headers })
  expect(archived.status(), await archived.text()).toBe(204)
  const creation = page.waitForResponse(response => new URL(response.url()).pathname === '/api/agents' && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Créer', exact: true }).click()
  const response = await creation
  expect(response.status(), await response.text()).toBe(201)
  const replacement = await response.json()
  expect(replacement.code).toBe(original.code)
  expect(replacement.id).not.toBe(original.id)
  await expect(dialog).toHaveCount(0)
  await page.reload()
  await expect(page.getByText('Remplaçant', { exact: true }).first()).toBeVisible()
  expect(errors).toEqual([])
})
