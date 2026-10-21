import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const width of [1440, 390]) {
  test(`Dataset browser history restores selections and protects unsaved JSON at ${width}px`, async ({ page, request }) => {
    const errors = collectPageErrors(page)
    const fixture = await (await request.post('/api/__test/seed')).json()
    await page.setViewportSize({ width, height: 900 })
    const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
    await page.goto('/user/login'); await refresh
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
    await page.locator('button[type=submit]').click()
    const session = await (await login).json()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    const headers = { Authorization: `Bearer ${session.access_token}` }
    const items = []
    for (const label of ['Alpha', 'Beta']) {
      const response = await request.post('/api/datasets', { headers, data: {
        title: `Synthetic navigation ${label}`, content: JSON.stringify({ value: label }),
      } })
      expect(response.ok(), await response.text()).toBeTruthy()
      items.push(await response.json())
    }
    await errors.settle()
    await page.goto('/dataset')
    const initialBackdrop = page.locator('.q-drawer__backdrop')
    if (width < 1024 && await initialBackdrop.isVisible()) await initialBackdrop.click({ position: { x: width - 10, y: 150 } })
    const search = page.getByRole('textbox', { name: /^(Search|Rechercher)$/, exact: true })
    const json = page.getByRole('textbox', { name: /^(JSON content|Contenu JSON)$/, exact: true })
    const openList = async () => {
      await page.locator('.mobile-taskbar').getByRole('button', { name: /^(Expand sidebar|Déployer la sidebar)$/, exact: true }).click()
      await page.getByRole('link', { name: /^(Datasets|Jeux de données)$/, exact: true }).click()
      const backdrop = page.locator('.q-drawer__backdrop')
      if (await backdrop.isVisible()) await backdrop.click({ position: { x: width - 10, y: 150 } })
    }
    const value = label => `{\n  "value": "${label}"\n}`
    const back = () => page.evaluate(() => window.history.back())
    const forward = () => page.evaluate(() => window.history.forward())
    await search.fill('Synthetic navigation')
    await page.getByRole('link', { name: items[0].title, exact: true }).click()
    await expect(json).toHaveValue(value('Alpha'))
    if (width < 1024) await openList()
    await page.getByRole('link', { name: items[1].title, exact: true }).click()
    await expect(json).toHaveValue(value('Beta'))
    if (width >= 1024) await page.getByRole('link', { name: items[1].title, exact: true }).click()
    await back()
    if (width < 1024) {
      await expect(json).toHaveCount(0)
      await expect(search).toHaveValue('Synthetic navigation')
      await back()
    }
    await expect(json).toHaveValue(value('Alpha'))
    await expect(page).toHaveURL(new RegExp(`/dataset/${items[0].id}$`))
    await json.fill('{')
    await back()
    const confirmation = page.getByRole('dialog')
    await confirmation.getByRole('button', { name: /^(Cancel|Annuler)$/, exact: true }).click()
    await expect(json).toHaveValue('{')
    await expect(page).toHaveURL(new RegExp(`/dataset/${items[0].id}$`))
    await back()
    await confirmation.getByRole('button', { name: /^(Discard changes|Abandonner les modifications)$/, exact: true }).click()
    await expect(page).toHaveURL(/\/dataset$/)
    await expect(json).toHaveCount(0)
    await expect(search).toHaveValue('Synthetic navigation')
    await forward()
    await expect(json).toHaveValue(value('Alpha'))
    await forward()
    if (width < 1024) {
      await expect(json).toHaveCount(0)
      await forward()
    }
    await expect(json).toHaveValue(value('Beta'))
    await expect(page).toHaveURL(new RegExp(`/dataset/${items[1].id}$`))
    await page.screenshot({ path: test.info().outputPath(`dataset-browser-history-${width}.png`), animations: 'disabled' })
    expect(errors()).toEqual([])
  })
}
