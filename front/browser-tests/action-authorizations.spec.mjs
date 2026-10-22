import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const width of [390, 1440]) {
  test(`mail approval preserves review content and exposes technical details on demand at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const row = { id: 'mail-review', agent_id: 7, approver_user_id: 1, source: 'domain', runtime: 'internal',
      capability_kind: 'tool', capability_name: 'mail_send', status: 'pending', can_answer: true,
      expires_at: '2026-12-01T12:00:00Z', preview: 'Mail: mail_send\ndomain/tool: mail_send\nsoftware\n{}',
      arguments: { prepared: { delivery_id: 'synthetic-delivery' } },
      presentation: { title: 'Envoyer un e-mail', fields: [
        { label: 'Destinataires', value: 'recipient@example.test' },
        { label: 'Copie cachée', value: 'hidden@example.test' },
        { label: 'Objet', value: 'Une nouvelle du jardin' },
        { label: 'Message', value: 'Bonjour,\n\nLes premières fleurs sont arrivées.\nÀ bientôt !' },
        { label: 'Pièces jointes', value: 'fleurs.txt' },
        { label: 'Version HTML (texte source)', value: '<script>window.syntheticMailExecuted = true</script>' },
      ] } }
    await jsonRoute(page, '**/api/tools/action-authorizations?*', { items: [row], total: 1 })
    await jsonRoute(page, '**/api/tools/action-authorizations/mail-review', row)
    await mount(page, 'app/connection/components/ActionAuthorizations.vue', {
      locale: 'fr', privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT'],
    })
    await page.getByRole('button', { name: 'Examiner la demande' }).click()
    const dialog = page.getByRole('dialog')
    for (const field of row.presentation.fields) await expect(dialog.getByText(field.value, { exact: true })).toBeVisible()
    expect(await page.evaluate(() => window.syntheticMailExecuted)).toBeUndefined()
    await expect(dialog.getByText(/synthetic-delivery/)).toBeHidden()
    await page.screenshot({ path: testInfo.outputPath('mail-review.png'), fullPage: true, animations: 'disabled' })
    await dialog.getByText('Détails techniques', { exact: true }).click()
    await expect(dialog.getByText(/synthetic-delivery/)).toBeVisible()
    // Application dialogs occupy the mobile viewport, so their backdrop is covered.
    if (width < 1024) await dialog.getByRole('button', { name: 'Annuler', exact: true }).first().click()
    else await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(dialog).toHaveCount(0)
  })
}

for (const [locale, reviewName, allowName] of [
  ['en', 'Review request', 'Allow this action'],
  ['fr', 'Examiner la demande', 'Autoriser cette action'],
]) {
  test(`an action is reviewed and answered once without changing remembered permissions (${locale})`, async ({ page }) => {
    const row = { id: 'action-a', agent_id: 7, approver_user_id: 1, source: 'mcp',
      capability_kind: 'tool', capability_name: 'file_write', status: 'pending',
      preview: 'Write the synthetic document', decision_source: null, can_answer: true,
      arguments: { path: 'console://example.txt', content: 'synthetic' },
      presentation: { title: 'Write the synthetic document', fields: [
        { label: 'Path', value: 'console://example.txt' }, { label: 'Content', value: 'synthetic' },
      ] } }
    const answers = [], queries = []
    await page.route('**/api/tools/action-authorizations?*', route => {
      queries.push(Object.fromEntries(new URL(route.request().url()).searchParams))
      return route.fulfill({ json: { items: [row], total: 1 } })
    })
    await page.route('**/api/tools/action-authorizations/action-a', route => route.fulfill({ json: row }))
    await page.route('**/api/tools/action-authorizations/action-a/answer', route => {
      answers.push(route.request().postDataJSON())
      row.status = 'approved'; row.can_answer = false; row.decision_source = 'human'
      return route.fulfill({ json: { accepted: true } })
    })
    await mount(page, 'app/connection/components/ActionAuthorizations.vue', {
      locale, privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT'],
    })
    await expect(page.getByText(row.preview, { exact: true })).toBeVisible()
    expect(queries[0].limit).toBe('50')
    await page.getByRole('button', { name: reviewName, exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('console://example.txt')
    await page.getByRole('dialog').getByRole('button', { name: allowName, exact: true }).click()
    await expect.poll(() => answers).toEqual([{ approved: true }])
    await expect(page.getByRole('dialog').getByRole('button', { name: allowName, exact: true })).toHaveCount(0)
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await page.getByRole('button', { name: reviewName, exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('console://example.txt')
    expect(answers).toHaveLength(1)
  })
}

test('mobile viewers can inspect a pending action without answering for another approver', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const row = { id: 'read-only', agent_id: 7, approver_user_id: 2, source: 'runtime',
    capability_kind: 'tool', capability_name: 'shell', status: 'pending', preview: 'Synthetic command', can_answer: false }
  await jsonRoute(page, '**/api/tools/action-authorizations?*', { items: [row], total: 1 })
  await jsonRoute(page, '**/api/tools/action-authorizations/read-only', row)
  await mount(page, 'app/connection/components/ActionAuthorizations.vue', { privileges: ['CONNECTION_ACCESS'] })
  await page.getByRole('button', { name: 'Review request' }).click()
  await expect(page.getByRole('dialog')).toContainText(row.preview)
  await expect(page.getByRole('button', { name: 'Allow this action' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Deny this action' })).toHaveCount(0)
})

for (const [locale, inspect, functionAlways, runtimeAlways] of [
  ['en', 'Review request', 'Always allow this function', 'Always allow this action type'],
  ['fr', 'Examiner la demande', 'Toujours autoriser cette fonction', 'Toujours autoriser ce type d’action'],
  ['zh', '查看请求', '始终允许此功能', '始终允许此类操作'],
]) {
  for (const source of ['mcp', 'runtime']) {
  const always = source === 'runtime' ? runtimeAlways : functionAlways
  test(`a permanent ${source} approval has explicit scope and survives an answer error (${locale})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const row = { id: 'topic-approval', agent_id: 7, approver_user_id: 1, source, runtime: 'hermes',
      capability_kind: 'tool', capability_name: 'topic_create', status: 'pending',
      preview: 'Create a synthetic topic', can_answer: true, can_remember: true }
    const answers = []
    await jsonRoute(page, '**/api/tools/action-authorizations?*', { items: [row], total: 1 })
    await page.route('**/api/tools/action-authorizations/topic-approval', route => route.fulfill({ json: row }))
    await page.route('**/api/tools/action-authorizations/topic-approval/answer', route => {
      answers.push(route.request().postDataJSON())
      if (answers.length === 1) return route.fulfill({ status: 409, json: { detail: 'Synthetic temporary failure' } })
      row.status = 'approved'; row.can_answer = false; row.can_remember = false
      return route.fulfill({ json: { accepted: true } })
    })
    await mount(page, 'app/connection/components/ActionAuthorizations.vue', {
      locale, privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT'],
    })
    await page.getByRole('button', { name: inspect, exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('topic_create')
    if (source === 'runtime') await expect(page.getByRole('dialog')).toContainText('hermes')
    await testInfo.attach(`${source}-${locale}`, { body: await page.getByRole('dialog').screenshot({ animations: 'disabled' }), contentType: 'image/png' })
    const button = page.getByRole('dialog').getByRole('button', { name: always, exact: true })
    await button.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('alert')).toBeVisible()
    await button.click()
    await expect.poll(() => answers).toEqual([{ approved: true, remember: true }, { approved: true, remember: true }])
    await expect(button).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('button', { name: inspect, exact: true }).click()
    await expect(button).toHaveCount(0)
  })
  }
}

test('remembered Harness action types can be revoked with error recovery and reopening', async ({ page }, testInfo) => {
  const row = { id: 'synthetic-rule', agent_id: 7, runtime: 'deepseek_harness', capability_name: 'write_file', active: true, can_revoke: true }
  let removed = false
  const writes = []
  await page.route('**/api/tools/action-authorizations/runtime-permissions?*', route => route.fulfill({ json: { items: removed ? [] : [row], total: removed ? 0 : 1 } }))
  await page.route('**/api/tools/action-authorizations/runtime-permissions/synthetic-rule', route => {
    writes.push(route.request().method())
    if (writes.length === 1) return route.fulfill({ status: 409, json: {} })
    removed = true
    return route.fulfill({ json: { revoked: true } })
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await mount(page, 'app/connection/components/RuntimePermissions.vue', { privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT'] })
  await expect(page.getByText('deepseek_harness · write_file')).toBeVisible()
  await testInfo.attach('remembered-runtime-mobile', { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' })
  await page.getByRole('button', { name: 'Revoke consent', exact: true }).click()
  await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(writes).toEqual([])
  await page.getByRole('button', { name: 'Revoke consent', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke consent', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke consent', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('deepseek_harness · write_file')).toHaveCount(0)
  expect(writes).toEqual(['DELETE', 'DELETE'])
})
