import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test(`Telegram setup creates the actual Tool and preserves its configuration on reopening`, async ({ page, request }, testInfo) => {
  const errors = collectPageErrors(page)
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok(), await seeded.text()).toBeTruthy()
  const fixture = await seeded.json()
  const refreshed = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refreshed
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  await page.locator('button[type=submit]').click()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  await errors.settle()
  await page.goto('/params/messaging')
  await page.getByRole('tab', { name: 'Telegram', exact: true }).click()
  const inactive = page.getByRole('switch', { name: 'Inactive', exact: true })
  if (await inactive.isVisible()) await inactive.click()
  await expect(page.getByRole('switch', { name: 'Active', exact: true })).toBeChecked()
  const guide = page.getByRole('region', { name: 'Guide de configuration', exact: true })
  const created = page.waitForResponse(response => response.url().endsWith('/api/tools') && response.request().method() === 'POST')
  await page.getByRole('button', { name: `Créer l’outil Telegram`, exact: true }).click()
  const result = await created
  expect(result.ok(), await result.text()).toBeTruthy()
  const tool = await result.json()
  expect(tool).toMatchObject({ code: 'telegram', label: 'Telegram',
    messenger_config: { service: 'telegram', settings: {}, param_map: { token: 'token' } },
    connection_schema: { params: { token: { type: 'password', required: true, default: '' } } } })
  await expect(guide.getByRole('link', { name: 'Ouvrir les outils et connexions', exact: true })).toBeVisible()
  // This agent has Chat, but no connection to this provider: no transport is tested.
  const reception = page.waitForResponse(response => response.url().endsWith(`/api/messenger/configuration/test?provider=telegram`))
  await page.getByRole('button', { name: 'Tester la réception', exact: true }).click()
  const receptionResult = await reception
  expect(receptionResult.ok(), await receptionResult.text()).toBeTruthy()
  expect(await receptionResult.json()).toEqual({ provider: 'telegram', ok: false, connections: [] })
  await expect(page.getByText('Aucun test lancé', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath(`telegram-setup-desktop.png`), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 1000 })
  await page.reload()
  // Authentication restores the shell asynchronously after a full reload.
  await expect(page.getByRole('tab', { name: 'Telegram', exact: true })).toBeVisible()
  if (await page.locator('.q-drawer__backdrop').isVisible()) {
    await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 150 } })
    await expect(page.locator('.q-drawer__backdrop')).not.toBeVisible()
  }
  const checked = page.waitForResponse(response => response.url().endsWith('/api/tools') && response.request().method() === 'GET')
  await page.getByRole('tab', { name: 'Telegram', exact: true }).click()
  await expect(guide.getByRole('link', { name: 'Ouvrir les outils et connexions', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: `Créer l’outil Telegram`, exact: true })).toHaveCount(0)
  const checkedResponse = await checked
  expect(checkedResponse.ok(), await checkedResponse.text()).toBeTruthy()
  const stored = await checkedResponse.json()
  expect(stored.filter(candidate => candidate.messenger_config?.service === 'telegram')).toHaveLength(1)
  await page.screenshot({ path: testInfo.outputPath(`telegram-setup-mobile.png`), fullPage: true, animations: 'disabled' })
  await guide.getByRole('link', { name: 'Configurer les comptes des agents', exact: true }).click()
  await expect(page).toHaveURL(/\/tools\?tab=connections$/)
  await expect(page.getByRole('tab', { name: 'Connexions', exact: true })).toHaveAttribute('aria-selected', 'true')
  await errors.settle()
  expect(errors()).toEqual([])
})

for (const width of [390, 1440]) test(`external reception is visible and the manager can deny from Permissions at ${width}px`, async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const errors = collectPageErrors(page)
  const seeded = await request.post('/api/__test/seed?mode=contact-authorization')
  expect(seeded.ok(), await seeded.text()).toBeTruthy()
  const fixture = await seeded.json()
  const refreshed = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refreshed
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  await page.locator('button[type=submit]').click()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  await errors.settle()
  await page.goto('/task?tab=conversations')
  if (width < 1024 && await page.locator('.q-drawer__backdrop').isVisible()) {
    await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 150 } })
  }
  await page.getByText('Synthetic external message awaiting manager consent', { exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('424200', { exact: true })).toBeVisible()
  await expect(dialog.getByText('synthetic_external_person', { exact: true })).toBeVisible()
  await expect(dialog).toContainText('Réponse en pause')
  await page.screenshot({ path: testInfo.outputPath('external-contact-paused.png'), fullPage: true, animations: 'disabled' })
  await dialog.getByRole('link', { name: 'Ouvrir les permissions', exact: true }).click()
  await expect(page).toHaveURL(/\/connection\/permissions/)
  const question = page.getByText(/Autorisez-vous .* à répondre à cette personne sur telegram/).first()
  await expect(question).toContainText('424200')
  const deny = page.getByRole('button', { name: 'Refuser et mémoriser', exact: true }).first()
  await expect(deny).toBeEnabled()
  await deny.focus()
  await page.keyboard.press('Enter')
  await expect(question).toHaveCount(0)
  await errors.settle()
  await page.goto('/task?tab=conversations')
  if (width < 1024 && await page.locator('.q-drawer__backdrop').isVisible()) {
    await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 150 } })
  }
  await page.getByText('Synthetic external message awaiting manager consent', { exact: true }).first().click()
  await expect(dialog).toContainText('Le manager a refusé les échanges avec cette personne.')
  await page.screenshot({ path: testInfo.outputPath('external-contact-denied.png'), fullPage: true, animations: 'disabled' })
  await errors.settle()
  expect(errors()).toEqual([])
})
