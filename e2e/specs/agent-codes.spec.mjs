import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'
import { selectOption } from '../select-option.mjs'

test('an occupied agent code is explained and becomes reusable after archival', async ({ page, request }) => {
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok()).toBeTruthy()
  const pageErrors = collectPageErrors(page)
  const fixture = await seeded.json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await pageErrors.settle()
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
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    const expectedConflict = path === '/api/agents' && response.status() === 400
    if (path.startsWith('/api/') && response.status() >= 400 && !expectedConflict) {
      errors.push(`${response.status()} ${response.request().method()} ${path}`)
    }
  })
  await pageErrors.settle()
  await page.goto('/agent')
  await page.getByRole('button', { name: 'Nouvel Agent', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel("Code de l'agent", { exact: true }).fill(original.code)
  await selectOption(page, dialog.getByRole('combobox', { name: 'Civilité *', exact: true }), `${original.title.label} (M)`)
  const firstName = `Remplaçant ${fixture.agent_id}`
  await dialog.getByLabel('Prénom *', { exact: true }).fill(firstName)
  await dialog.getByRole('button', { name: 'Créer', exact: true }).click()
  await expect(page.getByText('Ce code est déjà utilisé par un autre agent. Veuillez choisir un autre code.', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('Prénom *', { exact: true })).toHaveValue(firstName)

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
  await pageErrors.settle()
  await page.reload()
  await expect(page.getByText(firstName, { exact: true })).toBeVisible()
  expect([...errors, ...pageErrors()]).toEqual([])
})
