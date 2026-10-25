import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('manual pricing survives saving and reopening in the assembled application', async ({ page, request }, testInfo) => {
  test.setTimeout(120_000)
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok()).toBeTruthy()
  const fixture = await seeded.json()
  const errors = collectPageErrors(page)
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  const headers = { Authorization: `Bearer ${session.access_token}` }
  await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
  const models = await request.get('/api/llm-providers/llms', { headers })
  expect(models.ok()).toBeTruthy()
  const model = (await models.json()).find(item => item.primary_capability === 'chat')
  expect(model).toBeTruthy()
  expect((await request.put(`/api/llm-providers/llms/${model.id}`, { headers, data: {
    label: 'Synthetic pricing model', pricing_auto_update: true,
    cost_per_input_token: 1, cost_per_cached_input_token: .1, cost_per_output_token: 2,
  } })).ok()).toBeTruthy()

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    await errors.settle()
    await page.goto('/llm?tab=models')
    if (width < 1024) {
      await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), async backdrop => {
        await backdrop.click({ position: { x: width - 10, y: 200 } })
      })
    }
    const item = page.locator(width < 1024 ? '.llm-grid-card' : 'tbody tr')
      .filter({ hasText: 'Synthetic pricing model' })
    await item.getByRole('button', { name: 'Modifier', exact: true }).click()
    const dialog = page.getByRole('dialog')
    const nightly = dialog.getByRole('switch', { name: 'Actualiser les tarifs chaque nuit', exact: true })
    await expect(nightly).toBeChecked()
    await nightly.focus()
    await page.keyboard.press('Space')
    await expect(nightly).not.toBeChecked()
    await dialog.getByRole('spinbutton', { name: 'Coût input (par 1M tokens)', exact: true }).fill('7')
    await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    const stored = await request.get(`/api/llm-providers/llms/${model.id}`, { headers })
    expect(stored.ok()).toBeTruthy()
    expect(await stored.json()).toMatchObject({ pricing_auto_update: false, cost_per_input_token: 7 })
    await errors.settle()
    await page.reload()
    await item.getByRole('button', { name: 'Modifier', exact: true }).click()
    await expect(nightly).not.toBeChecked()
    await expect(dialog.getByRole('spinbutton', { name: 'Coût input (par 1M tokens)', exact: true })).toHaveValue('7')
    await dialog.screenshot({ path: testInfo.outputPath(`manual-pricing-${width}.png`), animations: 'disabled' })
    await nightly.click()
    await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click()
    await expect(dialog).toHaveCount(0)
  }
  await errors.settle()
  expect(errors()).toEqual([])
})
