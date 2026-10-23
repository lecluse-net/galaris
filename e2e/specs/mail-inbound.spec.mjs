import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const width of [390, 1440]) {
  test(`received email waits for consent and resumes from the journal at ${width}px`, async ({ page, request }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors = collectPageErrors(page)
    const seed = await request.post('/api/__test/seed?mode=mail-inbound')
    expect(seed.ok(), await seed.text()).toBeTruthy()
    const fixture = await seed.json()
    const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
    await page.goto('/user/login')
    await refresh
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    await page.locator('button[type=submit]').click()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    await errors.settle()
    await page.goto('/connection/mail')
    if (width < 1024 && await page.locator('.q-drawer__backdrop').isVisible()) {
      await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 150 } })
    }
    await page.getByRole('tab', { name: 'Réception', exact: true }).click()
    await page.getByLabel('Rechercher par agent, expéditeur ou objet').fill(fixture.inbound_subject)
    await expect(page.getByRole('button', { name: 'Voir le mail', exact: true })).toHaveCount(1)
    await expect(page.getByText(fixture.inbound_subject, { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Voir le mail', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Contenu non lu.')
    await expect(dialog).not.toContainText('Contenu synthétique du courriel reçu.')
    const allow = dialog.getByRole('button', { name: 'Autoriser ce mail', exact: true })
    await expect(allow).toBeEnabled()
    await page.screenshot({ path: testInfo.outputPath('pending-reception.png'), fullPage: true, animations: 'disabled' })
    await allow.focus()
    await page.keyboard.press('Enter')
    await expect(dialog).toHaveCount(0)
    const state = () => page.evaluate(async id => {
      const response = await fetch(`/api/mail/inbound/${id}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
      })
      if (!response.ok) throw new Error(`Mail reception HTTP ${response.status}`)
      return response.json()
    }, fixture.receipt_id)
    await expect.poll(async () => (await state()).status).toBe('admitted')
    await page.getByRole('button', { name: 'Actualiser', exact: true }).click()
    await page.getByRole('button', { name: 'Voir le mail', exact: true }).click()
    await expect(dialog).toContainText('Contenu synthétique du courriel reçu.')
    await expect(dialog.getByRole('button', { name: 'Autoriser ce mail', exact: true })).toHaveCount(0)
    if (width < 1024) await page.keyboard.press('Escape')
    else await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
    await expect(dialog).toHaveCount(0)
    await errors.settle()
  })
}
