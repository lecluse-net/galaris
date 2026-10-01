import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const [locale, toggleName, activateName, reviewName, allowName] of [
  ['en', 'YOLO mode', 'Enable YOLO', 'Review request', 'Allow this action'],
  ['fr', 'Mode YOLO', 'Activer YOLO', 'Examiner la demande', 'Autoriser cette action'],
]) {
  test(`YOLO needs an explicit acknowledgement and deactivation is immediate (${locale})`, async ({ page }) => {
    const writes = []
    await page.route('**/api/agents/7/yolo', route => {
      writes.push(route.request().postDataJSON())
      return route.fulfill({ json: { yolo: writes.at(-1).enabled, authorization_version: 3 } })
    })
    await mount(page, 'app/agent/components/AgentYoloControl.vue', {
      locale, props: { agent: { id: 7, yolo: false, authorization_version: 2 } },
    })
    await page.getByRole('switch', { name: new RegExp(toggleName) }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    expect(writes).toEqual([])
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(writes).toEqual([])
    await page.getByRole('switch').focus()
    await page.keyboard.press('Space')
    await page.getByRole('dialog').getByRole('button', { name: activateName, exact: true }).click()
    await expect.poll(() => writes).toEqual([{ enabled: true, acknowledged: true, expected_version: 2 }])
    await page.evaluate(() => window.testApp.setProps({ agent: { id: 7, yolo: true, authorization_version: 3 } }))
    await page.getByRole('switch').click()
    await expect.poll(() => writes.at(-1)).toEqual({ enabled: false, acknowledged: false, expected_version: 3 })
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test(`an action is reviewed and answered once without changing remembered permissions (${locale})`, async ({ page }) => {
    const row = { id: 'action-a', agent_id: 7, approver_user_id: 1, source: 'mcp',
      capability_kind: 'tool', capability_name: 'file_write', status: 'pending',
      preview: 'Write the synthetic document', decision_source: null, can_answer: true,
      arguments: { path: 'console://example.txt', content: 'synthetic' } }
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

for (const [locale, inspect, always] of [
  ['en', 'Review request', 'Always allow this function'],
  ['fr', 'Examiner la demande', 'Toujours autoriser cette fonction'],
  ['zh', '查看请求', '始终允许此功能'],
]) {
  test(`a permanent function approval has explicit scope and survives an answer error (${locale})`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const row = { id: 'topic-approval', agent_id: 7, approver_user_id: 1, source: 'mcp',
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
