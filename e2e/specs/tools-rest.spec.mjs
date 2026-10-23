import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('REST Tool configuration persists with connection credentials kept write-only', async ({ page, request }, testInfo) => {
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
  await expect(page.getByRole('tab', { name: 'Outils personnalisés', exact: true })).toHaveAttribute('aria-selected', 'true')
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
  for (const tab of ['connections', 'authorizations']) {
    await pageErrors.settle()
    const catalogueLoaded = page.waitForResponse(response => new URL(response.url()).pathname === '/api/tools' && response.request().method() === 'GET')
    await page.goto(`/tools?tab=${tab}`)
    await (await catalogueLoaded).finished()
    const filter = page.getByRole('combobox', { name: 'Filtrer par outil', exact: true })
    await filter.press('ArrowDown')
    const popup = page.getByRole('listbox')
    await expect(popup.getByText('Galaris', { exact: true }).first()).toBeVisible()
    await filter.press('End')
    await expect(popup.getByText('Personnalisé', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`${tab}-tool-groups.png`), animations: 'disabled' })
    await page.getByRole('option', { name: 'Synthetic REST service', exact: true }).click()
    await expect(page.getByRole('option', { name: 'Synthetic REST service', exact: true })).toHaveCount(0)
    if (tab === 'connections') {
      await expect(page.locator('tbody tr').filter({ hasText: 'Synthetic REST service' })).toContainText('Personnalisé')
    } else {
      await expect(page.getByRole('status').filter({ hasText: 'Personnalisé' })).toBeVisible()
    }
  }
  await pageErrors.settle()
  await page.goto('/tools')
  await page.getByRole('tab', { name: 'Outils personnalisés', exact: true }).click()
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
  // Prime the kept-alive Connections view before deleting the shared Tool.
  await page.getByRole('tab', { name: 'Connexions', exact: true }).click()
  await expect(page.locator('tbody tr').filter({ hasText: 'Synthetic REST service' })).toBeVisible()
  await page.getByRole('tab', { name: 'Outils', exact: true }).click()
  await page.getByRole('tab', { name: 'Outils personnalisés', exact: true }).click()
  await row.getByRole('button', { name: 'Supprimer', exact: true }).click()
  const deletion = page.getByRole('dialog')
  await expect(deletion).toContainText('Connexions des agents : 1')
  await expect(deletion).toContainText('Paramètres locaux et partagés')
  await deletion.getByRole('button', { name: 'Annuler', exact: true }).click()
  await expect(deletion).toHaveCount(0)
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: 'Supprimer', exact: true }).click()
  await expect(deletion).toContainText('Connexions des agents : 1')
  await page.screenshot({ path: testInfo.outputPath('tool-deletion-impact.png'), animations: 'disabled' })
  const removal = page.waitForResponse(response => response.request().method() === 'DELETE' && new URL(response.url()).pathname === `/api/tools/${tool.id}`)
  await deletion.getByRole('button', { name: 'Supprimer', exact: true }).click()
  expect((await removal).status()).toBe(204)
  await expect(deletion).toHaveCount(0)
  await expect(row).toHaveCount(0)
  const remaining = await request.get(`/api/connections?tool_id=${tool.id}`, { headers })
  expect(await remaining.json()).toEqual([])
  await page.getByRole('tab', { name: 'Connexions', exact: true }).click()
  await expect(page.locator('tbody tr').filter({ hasText: 'Synthetic REST service' })).toHaveCount(0)
  expect(failures).toEqual([])
  expect(pageErrors()).toEqual([])
})
