import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const [language, width, labels] of [
  ['fr', 390, { tab: 'Privilèges', category: 'Agents & équipes', edit: 'Modifier', save: 'Enregistrer', new: 'Nouvelle Liste', create: 'Créer' }],
  ['en', 1440, { tab: 'Privileges', category: 'Agents & teams', edit: 'Edit', save: 'Save', new: 'New List', create: 'Create' }],
]) test(`installed privilege categories retain translations and custom labels in ${language} at ${width}px`, async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const checked = async response => {
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const fixture = await checked(await request.post('/api/__test/seed'))
  const session = await checked(await request.post('/api/auth/login-json', {
    data: { email: fixture.email, password: fixture.password },
  }))
  const headers = { Authorization: `Bearer ${session.access_token}` }
  await checked(await request.put('/api/auth/me', { headers, data: { language } }))
  const categories = await checked(await request.get('/api/authorize/privilege-lists', { headers }))
  expect(categories.filter(item => item.translation_key)).toHaveLength(12)
  expect(categories.some(item => item.display_name === 'Chat')).toBe(false)
  const key = 'authorize.privilegeLists.defaults.agentsTeams'
  const installed = categories.find(item => item.translation_key === key)
  expect(installed.display_name).toBe(key)

  const errors = collectPageErrors(page)
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  await page.locator('button[type=submit]').click()
  await expect(page).not.toHaveURL(/\/user\/login$/)
  await page.goto('/authorize')
  if (width < 1024) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), async backdrop => {
    await backdrop.click({ position: { x: width - 10, y: 200 } })
  })
  await page.getByRole('tab', { name: labels.tab, exact: true }).click()
  const card = page.locator('.privilege-list-card').filter({ has: page.getByText(labels.category, { exact: true }) })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: labels.edit, exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('textbox')).toHaveValue(labels.category)
  const saved = page.waitForResponse(response => response.url().endsWith(`/api/authorize/privilege-lists/${installed.id}`) && response.request().method() === 'PUT')
  await dialog.getByRole('button', { name: labels.save, exact: true }).click()
  const unchanged = await checked(await saved)
  expect(unchanged.display_name).toBe(key)
  expect(unchanged.translation_key).toBe(key)
  await expect(dialog).toHaveCount(0)

  const custom = `Synthetic category ${language}`
  await page.getByRole('button', { name: labels.new, exact: true }).click()
  await dialog.getByRole('textbox').fill(custom)
  await dialog.getByRole('button', { name: labels.create, exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText(custom, { exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('tab', { name: labels.tab, exact: true }).click()
  await expect(card).toBeVisible()
  await expect(page.getByText(custom, { exact: true })).toBeVisible()
  const persisted = await checked(await request.get('/api/authorize/privilege-lists', { headers }))
  expect(persisted.find(item => item.display_name === custom).translation_key).toBeNull()
  await expect(page.locator('.role-manager')).not.toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('installed-categories.png'), fullPage: true })
  await errors.settle()
  expect(errors()).toEqual([])
})
