import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'
import { notificationPrompt } from '../notification-prompt.mjs'
import { withSidebarDismissal } from '../sidebar.mjs'

for (const [provider, service] of [['Telegram', 'telegram'], ['Matrix', 'matrix']]) {
test(`${provider} setup creates the actual Tool and preserves its configuration on reopening`, async ({ page, request }, testInfo) => {
  const errors = collectPageErrors(page)
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok(), await seeded.text()).toBeTruthy()
  const fixture = await seeded.json()
  const matrixHomeserver = `https://matrix-${fixture.agent_id}.example.test`
  const refreshed = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refreshed
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authenticated = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authenticated).json()
  const headers = { Authorization: `Bearer ${session.access_token}` }
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  await errors.settle()
  await page.goto('/params/messaging')
  await page.getByRole('tab', { name: provider, exact: true }).click()
  if (service === 'matrix') {
    const homeserver = page.getByRole('textbox', { name: 'URL du homeserver Matrix', exact: true })
    const saved = page.waitForResponse(response => response.url().endsWith('/api/params/MESSENGER_MATRIX_HOMESERVER') && response.request().method() === 'PUT')
    await homeserver.fill(matrixHomeserver)
    await homeserver.press('Tab')
    const savedResult = await saved
    expect(savedResult.ok(), await savedResult.text()).toBeTruthy()
  }
  const inactive = page.getByRole('switch', { name: 'Inactive', exact: true })
  if (await inactive.isVisible()) await inactive.click()
  await expect(page.getByRole('switch', { name: 'Active', exact: true })).toBeChecked()
  const guide = page.getByRole('region', { name: 'Guide de configuration', exact: true })
  const created = page.waitForResponse(response => response.url().endsWith('/api/tools') && response.request().method() === 'POST')
  await page.getByRole('button', { name: `Créer l’outil ${provider}`, exact: true }).click()
  const result = await created
  expect(result.ok(), await result.text()).toBeTruthy()
  const tool = await result.json()
  expect(tool).toMatchObject({ code: service, label: provider,
    messenger_config: { service, settings: service === 'matrix' ? { homeserver: matrixHomeserver } : {}, param_map: { token: 'token' } },
    connection_schema: { params: { token: { type: 'password', required: service === 'telegram', default: '' } } } })
  if (service === 'matrix') expect(tool).toMatchObject({
    messenger_config: { param_map: { user_id: 'user_id', token: 'token', password: 'password' } },
    connection_schema: { params: {
      user_id: { type: 'string', required: true, default: '' },
      password: { type: 'password', required: false, default: '' },
    } },
  })
  await expect(guide.getByRole('link', { name: 'Ouvrir les outils et connexions', exact: true })).toBeVisible()
  // This agent has Chat, but no connection to this provider: no transport is tested.
  const reception = page.waitForResponse(response => response.url().endsWith(`/api/messenger/configuration/test?provider=${service}`))
  await page.getByRole('button', { name: 'Tester la réception', exact: true }).click()
  const receptionResult = await reception
  expect(receptionResult.ok(), await receptionResult.text()).toBeTruthy()
  expect(await receptionResult.json()).toEqual({ provider: service, ok: false, connections: [] })
  await expect(page.getByText('Aucun test lancé', { exact: true })).toBeVisible()
  if (service === 'matrix') {
    // The API error contract is exercised here in the assembled page; the real
    // bridge and its filtered homeserver request are covered by backend tests.
    const detail = 'Les salons Matrix chiffrés ne sont pas pris en charge par Galaris (détectés : 1). Leurs messages ne peuvent pas être déchiffrés et ne créent aucun round. Utilisez un salon non chiffré.'
    await page.route('**/api/messenger/configuration/test?provider=matrix', route => route.fulfill({ json: {
      provider: service, ok: false, connections: [{ connection_id: 91, agent_id: fixture.agent_id, provider: service,
        ok: false, receiving: true, last_received_at: null, detail }],
    } }))
    await page.getByRole('button', { name: 'Tester la réception', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: detail })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('matrix-encryption-error-desktop.png'), fullPage: true, animations: 'disabled' })
    await page.unroute('**/api/messenger/configuration/test?provider=matrix')
  }
  await page.screenshot({ path: testInfo.outputPath(`${service}-setup-desktop.png`), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 1000 })
  await page.reload()
  // Authentication restores the shell asynchronously after a full reload.
  await expect(page.getByRole('tab', { name: provider, exact: true })).toBeVisible()
  const checked = page.waitForResponse(response => response.url().endsWith('/api/tools') && response.request().method() === 'GET')
  await withSidebarDismissal(page, () => page.getByRole('tab', { name: provider, exact: true }).click())
  await expect(guide.getByRole('link', { name: 'Ouvrir les outils et connexions', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: `Créer l’outil ${provider}`, exact: true })).toHaveCount(0)
  const checkedResponse = await checked
  expect(checkedResponse.ok(), await checkedResponse.text()).toBeTruthy()
  const stored = await checkedResponse.json()
  expect(stored.filter(candidate => candidate.messenger_config?.service === service)).toHaveLength(1)
  await page.screenshot({ path: testInfo.outputPath(`${service}-setup-mobile.png`), fullPage: true, animations: 'disabled' })
  await guide.getByRole('link', { name: 'Configurer les comptes des agents', exact: true }).click()
  await expect(page).toHaveURL(/\/tools\?tab=connections$/)
  await expect(page.getByRole('tab', { name: 'Connexions', exact: true })).toHaveAttribute('aria-selected', 'true')
  await errors.settle()
  expect(errors()).toEqual([])
  const removed = await request.delete(`/api/tools/${tool.id}`, { headers })
  expect(removed.status(), await removed.text()).toBe(204)
})
}

for (const width of [390, 1440]) test(`external reception is visible and the manager can deny from Permissions at ${width}px`, async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const errors = collectPageErrors(page)
  await page.addLocatorHandler(notificationPrompt(page), prompt => prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  const seeded = await request.post('/api/__test/seed?mode=contact-authorization')
  expect(seeded.ok(), await seeded.text()).toBeTruthy()
  const fixture = await seeded.json()
  const refreshed = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refreshed
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authenticated = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authenticated).json()
  const headers = { Authorization: `Bearer ${session.access_token}` }
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  await errors.settle()
  await page.goto('/task?tab=conversations')
  await withSidebarDismissal(page, () => page.getByText('Synthetic external message awaiting manager consent', { exact: true }).first().click())
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('424200', { exact: true })).toBeVisible()
  await expect(dialog.getByText('synthetic_external_person', { exact: true })).toBeVisible()
  await expect(dialog).toContainText('Réponse en pause')
  await page.screenshot({ path: testInfo.outputPath('external-contact-paused.png'), fullPage: true, animations: 'disabled' })
  await dialog.getByRole('link', { name: 'Ouvrir les permissions', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/permissions\\?agent_id=${fixture.agent_id}`))
  const question = page.getByText(/Autorisez-vous .* à répondre à cette personne sur telegram/).first()
  await expect(question).toContainText('424200')
  const deny = page.getByRole('button', { name: 'Refuser et mémoriser', exact: true }).first()
  await expect(deny).toBeEnabled()
  await deny.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Refuser et mémoriser', exact: true })).toHaveCount(0)
  await errors.settle()
  await page.goto('/task?tab=conversations')
  await withSidebarDismissal(page, () => page.getByText('Synthetic external message awaiting manager consent', { exact: true }).first().click())
  await expect(dialog).toContainText('Le manager a refusé les échanges avec cette personne.')
  await page.screenshot({ path: testInfo.outputPath('external-contact-denied.png'), fullPage: true, animations: 'disabled' })
  await errors.settle()
  expect(errors()).toEqual([])
  // Remove only this scenario's synthetic transport and its dependent conversation.
  const impact = await request.get(`/api/tools/${fixture.external_tool_id}/deletion-impact`, { headers })
  expect(impact.ok(), await impact.text()).toBeTruthy()
  const { version } = await impact.json()
  const removed = await request.delete(`/api/tools/${fixture.external_tool_id}?cascade=true&expected_version=${encodeURIComponent(version)}`, { headers })
  expect(removed.status(), await removed.text()).toBe(204)
})
