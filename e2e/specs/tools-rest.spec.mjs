import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('REST Tool configuration persists with connection credentials kept write-only', async ({ page, request }) => {
  const pageErrors = collectPageErrors(page)
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const failures = []
  page.on('response', response => {
    if (new URL(response.url()).pathname.startsWith('/api/') && response.status() >= 400) {
      failures.push(`${response.status()} ${new URL(response.url()).pathname}`)
    }
  })
  await pageErrors.settle()
  await page.goto('/tools')
  await page.getByRole('button', { name: 'Nouvel outil', exact: true }).click()
  const editor = page.getByRole('dialog')
  const code = `synthetic_rest_${fixture.agent_id}`
  await editor.getByLabel('Nom technique *', { exact: true }).fill(code)
  await editor.getByLabel('Libellé *', { exact: true }).fill('Synthetic REST service')
  await editor.getByRole('switch', { name: 'Activer API', exact: true }).click()
  await expect(editor.getByLabel('Adresse de base de l’API', { exact: true })).toHaveValue('${connection:api_url}')
  const create = page.waitForResponse(response => response.url().endsWith('/api/tools') && response.request().method() === 'POST')
  await editor.getByRole('button', { name: 'Créer', exact: true }).click()
  const createdResponse = await create
  expect(createdResponse.ok(), await createdResponse.text()).toBe(true)
  const tool = await createdResponse.json()
  await expect(editor).toHaveCount(0)
  expect(tool.has_api).toBe(true)
  const connectionResponse = await request.post('/api/connections', { headers, data: { tool_id: tool.id, agent_id: fixture.agent_id, active: true } })
  expect(connectionResponse.ok(), await connectionResponse.text()).toBe(true)
  const connection = await connectionResponse.json()
  const token = 'synthetic-rest-connection-token'
  const globals = await request.put(`/api/tools/${tool.id}/global-params`, { headers, data: { params: {
    api_url: { value: 'https://api.example.test/v1' }, api_token: { value: token },
  } } })
  expect(globals.ok(), await globals.text()).toBe(true)
  expect(await globals.text()).not.toContain(token)
  const projection = await request.get(`/api/connections/${connection.id}/params`, { headers })
  expect(projection.ok(), await projection.text()).toBe(true)
  expect(await projection.text()).not.toContain(token)
  const exported = await request.get(`/api/tools/${tool.id}/export`, { headers })
  expect(await exported.text()).not.toContain(token)
  await page.reload()
  const row = page.locator('tbody tr').filter({ hasText: code })
  await row.getByRole('button', { name: "Modifier l'outil", exact: true }).click()
  await editor.getByRole('tab', { name: 'API REST', exact: true }).click()
  await expect(editor.getByLabel('Adresse de base de l’API', { exact: true })).toHaveValue('${connection:api_url}')
  await editor.getByRole('switch', { name: 'Activer API', exact: true }).click()
  const save = page.waitForResponse(response => response.url().endsWith(`/api/tools/${tool.id}`) && response.request().method() === 'PUT')
  await editor.getByRole('button', { name: 'Enregistrer', exact: true }).click()
  const updated = await save
  expect(updated.ok(), await updated.text()).toBe(true)
  expect((await updated.json()).rest_config).toBeNull()
  await expect(editor).toHaveCount(0)
  expect(failures).toEqual([])
  expect(pageErrors()).toEqual([])
})
