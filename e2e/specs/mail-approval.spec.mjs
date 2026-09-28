import { test, expect } from '@playwright/test'

for (const scenario of [
  { label: 'Autoriser l’envoi', status: 'sent', mobile: false },
  { label: 'Refuser', status: 'rejected', mobile: true },
]) {
  test(`mail approval from private Chat: ${scenario.status}`, async ({ page, request }) => {
    if (scenario.mobile) await page.setViewportSize({ width: 390, height: 844 })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
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
    await page.goto(`/chat?room=${fixture.rooms[1]}`)
    await expect(page.locator('.message-timeline')).toContainText('Compte rendu synthétique')
    await expect(page.locator('.message-timeline')).toContainText('recipient@example.org')
    await expect(page.locator('.message-timeline')).toContainText('archive@example.org')
    await expect(page.locator('.message-timeline')).toContainText('rapport.txt')
    const action = page.getByRole('button', { name: scenario.label, exact: true })
    await expect(action).toBeEnabled()
    // Keyboard activation exercises the same persisted choice as a pointer click.
    await action.focus()
    await page.keyboard.press('Enter')
    const status = () => page.evaluate(async id => {
      const response = await fetch(`/api/mail/outbound/${id}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
      })
      if (!response.ok) throw new Error(`Mail journal HTTP ${response.status}`)
      return (await response.json()).status
    }, fixture.delivery_id)
    await expect.poll(status).toBe(scenario.status)
    await page.reload()
    await expect(page.locator('.message-timeline')).toContainText('Compte rendu synthétique')
    await expect(page.getByRole('button', { name: scenario.label, exact: true })).toBeDisabled()
    expect(await status()).toBe(scenario.status)
    expect(errors).toEqual([])
  })
}
