import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const receipt = {
  id: 'synthetic-receipt', connection_id: 5, agent_id: 7, agent_label: 'Synthetic agent',
  sender_address: 'sender@example.test', subject: 'Synthetic incoming email', message_ref: 'synthetic-ref',
  to_addresses: ['agent@example.test'], known_contact: false, status: 'pending_approval',
  authorization_id: 'synthetic-authorization', authorization_status: 'pending', can_review: true,
  created_at: '2026-10-01T12:00:00Z', authorized_at: null, admitted_at: null, read_at: null, error: null,
}

async function setup(page, options = {}) {
  await jsonRoute(page, '**/api/mail/outbound?*', { items: [], total: 0, limit: 50, offset: 0 })
  await jsonRoute(page, '**/api/mail/outbound/agents', [{ id: 7, label: 'Synthetic agent' }])
  await mount(page, 'app/connection/pages/mail.vue', {
    privileges: options.readonly ? ['CONNECTION_ACCESS'] : ['CONNECTION_ACCESS', 'CONNECTION_EDIT'],
  })
  await page.getByRole('tab', { name: 'Reception', exact: true }).click()
}

for (const width of [390, 1440]) {
  for (const remember of [false, true]) {
    test(`email processing consent ${remember ? 'always' : 'once'} at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 })
      const answers = []
      const queries = []
      await page.route('**/api/mail/inbound?*', route => {
        queries.push(Object.fromEntries(new URL(route.request().url()).searchParams))
        return route.fulfill({ json: { items: [receipt], total: 1, offset: 0, limit: 50 } })
      })
      await jsonRoute(page, '**/api/mail/inbound/synthetic-receipt', { ...receipt, content: null })
      await jsonRoute(page, '**/api/tools/action-authorizations/synthetic-authorization', {
        id: receipt.authorization_id, can_answer: true, can_remember: true,
      })
      await page.route('**/api/tools/action-authorizations/synthetic-authorization/answer', async route => {
        answers.push(route.request().postDataJSON())
        await route.fulfill({ json: { accepted: true } })
      })
      await setup(page)
      await expect(page.getByText(receipt.subject, { exact: true })).toBeVisible()
      expect(queries[0].limit).toBe('50')
      await page.getByRole('button', { name: 'View email', exact: true }).click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toContainText(receipt.sender_address)
      await expect(dialog).toContainText('Content unread.')
      await page.screenshot({ path: testInfo.outputPath('mail-reception.png'), fullPage: true, animations: 'disabled' })
      const button = dialog.getByRole('button', { name: remember ? 'Always process emails' : 'Allow this email', exact: true })
      await button.focus()
      await page.keyboard.press('Enter')
      await expect.poll(() => answers).toEqual([{ approved: true, ...(remember ? { remember: true } : {}) }])
      await expect(dialog).toHaveCount(0)
      await page.getByRole('tab', { name: 'Sending', exact: true }).click()
      await expect(page.getByRole('region', { name: 'Delivery journal', exact: true })).toBeVisible()
    })
  }
}

test('received email content stays inert and read-only viewers cannot grant consent', async ({ page }) => {
  await jsonRoute(page, '**/api/mail/inbound?*', { items: [receipt], total: 1 })
  const content = '<script>window.syntheticAttack = true</script> Synthetic body'
  await jsonRoute(page, '**/api/mail/inbound/synthetic-receipt', { ...receipt, status: 'admitted',
    content: { body: content, body_end: content.length, body_total: content.length, attachments: [] } })
  await setup(page, { readonly: true })
  await page.getByRole('button', { name: 'View email', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText(content)
  await expect(page.getByRole('button', { name: 'Allow this email' })).toHaveCount(0)
  expect(await page.evaluate(() => window.syntheticAttack)).toBeUndefined()
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('inbound journal recovers from a failed load and keeps sender filtering', async ({ page }) => {
  let failed = true
  const queries = []
  await page.route('**/api/mail/inbound?*', route => {
    queries.push(Object.fromEntries(new URL(route.request().url()).searchParams))
    return route.fulfill(failed ? { status: 503, json: {} } : { json: { items: [receipt], total: 1 } })
  })
  await setup(page)
  await expect(page.getByRole('alert')).toBeVisible()
  failed = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText(receipt.subject, { exact: true })).toBeVisible()
  await page.getByLabel('Search by agent, sender or subject').fill('sender@example.test')
  await expect.poll(() => queries.at(-1).search).toBe('sender@example.test')
})

test('a late processing decision preserves the next opened email', async ({ page }) => {
  const next = { ...receipt, id: 'synthetic-next', subject: 'Another synthetic email', can_review: false }
  await jsonRoute(page, '**/api/mail/inbound?*', { items: [receipt, next], total: 2 })
  await jsonRoute(page, '**/api/mail/inbound/synthetic-receipt', { ...receipt, content: null })
  await jsonRoute(page, '**/api/mail/inbound/synthetic-next', { ...next, content: null })
  await jsonRoute(page, '**/api/tools/action-authorizations/synthetic-authorization', {
    id: receipt.authorization_id, can_answer: true, can_remember: false,
  })
  let answerRoute
  await page.route('**/api/tools/action-authorizations/synthetic-authorization/answer', route => { answerRoute = route })
  await setup(page)
  await page.getByRole('row').filter({ hasText: receipt.subject }).getByRole('button', { name: 'View email' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Allow this email', exact: true }).click()
  await expect.poll(() => Boolean(answerRoute)).toBe(true)
  await dialog.getByRole('button', { name: 'Close', exact: true }).last().click()
  await expect(dialog).toHaveCount(0)
  await page.getByRole('row').filter({ hasText: next.subject }).getByRole('button', { name: 'View email' }).click()
  await expect(dialog).toContainText(next.subject)
  await answerRoute.fulfill({ json: { accepted: true } })
  await expect(page.getByText('Decision recorded. Authorized processing will resume automatically.', { exact: true })).toBeVisible()
  await expect(dialog).toContainText(next.subject)
  await dialog.getByRole('button', { name: 'Close', exact: true }).last().click()
  await expect(dialog).toHaveCount(0)
})
