import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const scenario of [
  { label: 'Autoriser l’envoi', status: 'sent', mobile: false, mode: 'mail', channel: 'chat' },
  { label: 'Refuser', status: 'rejected', mobile: true, mode: 'mail', channel: 'chat' },
  { label: 'Autoriser cette action', status: 'sent', mobile: false, mode: 'mail-common', channel: 'chat' },
  { label: 'Refuser cette action', status: 'rejected', mobile: true, mode: 'mail-common', channel: 'chat' },
  { label: 'Autoriser cette action', status: 'sent', mobile: false, mode: 'mail-common', channel: 'journal' },
  { label: 'Refuser cette action', status: 'rejected', mobile: true, mode: 'mail-common', channel: 'journal' },
]) {
  test(`mail approval from ${scenario.channel} (${scenario.mode}): ${scenario.status}`, async ({ page, request }, testInfo) => {
    if (scenario.mobile) await page.setViewportSize({ width: 390, height: 844 })
    const errors = collectPageErrors(page)
    const response = await request.post(`/api/__test/seed?mode=${scenario.mode}`)
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
    if (scenario.channel === 'journal') {
      await errors.settle()
      await page.goto('/connection/mail')
      const pending = page.getByRole('region', { name: 'En attente d’envoi', exact: true })
      await expect(pending.getByText('Compte rendu synthétique', { exact: true }).first()).toBeVisible()
      if (scenario.mobile && await page.locator('.q-drawer__backdrop').isVisible()) {
        await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 150 } })
        await expect(page.locator('.q-drawer__backdrop')).toBeHidden()
      }
      await pending.getByRole('button', { name: 'Examiner', exact: true }).click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toContainText('recipient@example.org')
      await expect(dialog).toContainText('archive@example.org')
      await expect(dialog).toContainText('rapport.txt')
      await page.screenshot({ path: testInfo.outputPath('mail-journal-review.png'), fullPage: true, animations: 'disabled' })
      const endpoint = scenario.status === 'sent' ? 'approve' : 'reject'
      const answered = page.waitForResponse(response => response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/mail/outbound/${fixture.delivery_id}/${endpoint}`)
      await dialog.getByRole('button', { name: scenario.status === 'sent' ? 'Valider et envoyer' : 'Rejeter', exact: true }).click()
      const result = await answered
      expect(result.ok(), await result.text()).toBeTruthy()
      if (scenario.status === 'sent') {
        const receipt = await result.json()
        expect(['claimed', 'submitting', 'sent']).toContain(receipt.status)
        await expect(page.getByText(receipt.status === 'sent'
          ? 'Le mail a été validé et soumis au serveur SMTP.'
          : 'Accord enregistré. La tâche reprendra l’envoi du mail.', { exact: true })).toBeVisible()
      }
      await expect(dialog).toHaveCount(0)
    } else {
      // Keyboard activation exercises the same persisted choice as a pointer click.
      await action.focus()
      const answer = page.waitForResponse(response => response.request().method() === 'POST'
        && /\/interactions\/[^/]+\/answer$/.test(new URL(response.url()).pathname))
      await page.keyboard.press('Enter')
      const answered = await answer
      expect(answered.ok()).toBeTruthy()
      await answered.finished()
    }
    const status = () => page.evaluate(async id => {
      const response = await fetch(`/api/mail/outbound/${id}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
      })
      if (!response.ok) throw new Error(`Mail journal HTTP ${response.status}`)
      return (await response.json()).status
    }, fixture.delivery_id)
    await expect.poll(status).toBe(scenario.status)
    await errors.settle()
    await page.goto(`/chat?room=${fixture.rooms[1]}`)
    await expect(page.locator('.message-timeline')).toContainText('Compte rendu synthétique')
    await expect(page.getByRole('button', { name: scenario.label, exact: true })).toBeDisabled()
    expect(await status()).toBe(scenario.status)
    expect(errors()).toEqual([])
  })
}
