import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const width of [1440, 390]) {
  test(`Memory file indexing loads real API and rejects excluded roots at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 900 })
    const errors = collectPageErrors(page)
    const fixture = await (await request.post('/api/__test/seed')).json()
    const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
    await errors.settle()
    await page.goto('/user/login')
    await refresh
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
    await page.locator('button[type=submit]').click()
    await authentication
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    await errors.settle()
    await page.goto(`/memory?agent=${fixture.agent_id}`)
    if (width < 1024) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop => backdrop.click({ position: { x: 380, y: 150 } }), { times: 1 })
    const progress = page.waitForResponse(response => new URL(response.url()).pathname === '/api/file-share/indexing')
    await page.getByText('Indexation des fichiers', { exact: true }).click()
    expect((await progress).status()).toBe(200)
    await expect(page.getByText('Aucun parcours pour cet agent.')).toBeVisible()
    await page.getByLabel('Racine source (URI)').fill('document://')
    const rejection = page.waitForResponse(response => new URL(response.url()).pathname === '/api/file-share/indexing' && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Indexer maintenant', exact: true }).click()
    expect((await rejection).status()).toBe(403)
    await expect(page.getByText('L’indexation n’a pas pu être chargée ou modifiée.')).toBeVisible()
    await page.getByRole('button', { name: 'Réessayer', exact: true }).click()
    await expect(page.getByText('L’indexation n’a pas pu être chargée ou modifiée.')).toHaveCount(0)
    await errors.settle()
    expect(errors()).toEqual([])
  })
}
