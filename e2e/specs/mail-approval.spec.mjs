import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const scenario of [
  { label: 'Autoriser l’envoi', status: 'sent', mobile: false },
  { label: 'Refuser', status: 'rejected', mobile: true },
]) {
  test(`mail approval from private Chat: ${scenario.status}`, async ({ page, request }) => {
    if (scenario.mobile) await page.setViewportSize({ width: 390, height: 844 })
    const errors = collectPageErrors(page)
    const response = await request.post('/api/__test/seed?mode=mail')
    expect(response.ok(), await response.text()).toBeTruthy()
    const fixture = await response.json()
    const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
    await page.goto('/user/login')
    await refresh
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    await page.locator('button[type=submit]').click()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    await errors.settle()
    await page.goto(`/chat?room=${fixture.rooms[1]}`)
    await expect(page.locator('.message-timeline')).toContainText('Compte rendu synthétique')
    await expect(page.locator('.message-timeline')).toContainText('recipient@example.org')
    await expect(page.locator('.message-timeline')).toContainText('archive@example.org')
    await expect(page.locator('.message-timeline')).toContainText('rapport.txt')
    const action = page.getByRole('button', { name: scenario.label, exact: true })
    await expect(action).toBeEnabled()
    // Keyboard activation exercises the same persisted choice as a pointer click.
    await action.focus()
    const answer = page.waitForResponse(response => response.request().method() === 'POST'
      && /\/interactions\/[^/]+\/answer$/.test(new URL(response.url()).pathname))
    await page.keyboard.press('Enter')
    const answered = await answer
    expect(answered.ok()).toBeTruthy()
    await answered.finished()
    const status = () => page.evaluate(async id => {
      const response = await fetch(`/api/mail/outbound/${id}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
      })
      if (!response.ok) throw new Error(`Mail journal HTTP ${response.status}`)
      return (await response.json()).status
    }, fixture.delivery_id)
    await expect.poll(status).toBe(scenario.status)
    await errors.settle()
    await page.reload()
    await expect(page.locator('.message-timeline')).toContainText('Compte rendu synthétique')
    await expect(page.getByRole('button', { name: scenario.label, exact: true })).toBeDisabled()
    expect(await status()).toBe(scenario.status)
    expect(errors()).toEqual([])
  })
}
