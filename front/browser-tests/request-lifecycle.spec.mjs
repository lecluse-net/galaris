import { test, expect, mount, jsonRoute } from './fixtures.mjs'

test('a completed Topic save cannot close or replace a reopened draft', async ({ page }) => {
  let release
  await jsonRoute(page, '**/api/topics/keywords', [])
  await page.route('**/api/topics', async route => {
    const input = route.request().postDataJSON()
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { ...input, id: 'synthetic-saved-topic', revision: 1 } })
  })
  await mount(page, 'app/topic/components/TopicFormDialog.vue', { props: { modelValue: true } })
  const dialog = page.getByRole('dialog'), title = dialog.getByRole('textbox', { name: 'Dossier', exact: true })
  await title.fill('Synthetic first draft')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  try {
    await expect.poll(() => Boolean(release)).toBe(true)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await page.evaluate(() => window.testApp.setProps({ modelValue: true }))
    await title.fill('Synthetic reopened draft')
    const response = page.waitForResponse('**/api/topics')
    release(); await response
    await expect(title).toHaveValue('Synthetic reopened draft')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
  } finally { release?.() }
})

test('a purge dialog closes during its request and its completion preserves another confirmation', async ({ page }) => {
  let release
  await page.route('**/api/tasks/cleanup', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ status: 204 })
  })
  await mount(page, 'core/params/components/LogCleanupPanel.vue', { privileges: ['TASK_PURGE', 'LLM_CALL_PURGE'] })
  await page.getByRole('button', { name: /processed tasks/i }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Purge', exact: true }).click()
  try {
    await expect.poll(() => Boolean(release)).toBe(true)
    await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
    await expect(dialog).toHaveCount(0)
    await page.getByRole('button', { name: 'Archive LLM calls', exact: true }).click()
    await expect(dialog).toContainText('Archive completed LLM calls?')
    const response = page.waitForResponse('**/api/tasks/cleanup')
    release(); await response
    await expect(dialog).toContainText('Archive completed LLM calls?')
    await expect(dialog.getByRole('button', { name: 'Purge', exact: true })).toBeEnabled()
  } finally { release?.() }
})

test('voice filters changed during a slow read retrieve their own results', async ({ page }) => {
  let release
  const queries = []
  await page.route('**/api/voice/conversations?*', async route => {
    const status = new URL(route.request().url()).searchParams.get('status'); queries.push(status)
    if (!status) await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { items: [{ id: status ? 'current' : 'old', agent_id: 7, agent_name: 'Synthetic agent', turns: [], topic_id: null,
      status: status || 'COMPLETED', started_at: '2026-01-01T10:00:00Z', duration: 1, turn_count: 0, transport_kind: 'matrix', room_id: status ? 'Current error room' : 'Obsolete room' }],
      total: 1, page: 1, page_size: 50, summary: { active: 0, completed: 0, cancelled: 0, errors: 1 } } })
  })
  await mount(page, 'app/voice/components/VoiceCallHistory.vue', { privileges: ['VOICE_HISTORY_ACCESS'] })
  try {
    await expect.poll(() => Boolean(release)).toBe(true)
    await page.getByRole('combobox', { name: 'Filter by status', exact: true }).click()
    await page.getByRole('option', { name: 'Error', exact: true }).click()
    await expect(page.getByText('Current error room', { exact: true })).toBeVisible()
    const old = page.waitForResponse(response => response.url().includes('/voice/conversations?') && !new URL(response.url()).searchParams.has('status'))
    release(); await old
    await expect(page.getByText('Current error room', { exact: true })).toBeVisible()
    await expect(page.getByText('Obsolete room', { exact: true })).toHaveCount(0)
    expect(queries).toContain('ERROR')
  } finally { release?.() }
})

test('conversation polling publishes a slow first response without overlapping reads', async ({ page }) => {
  await page.clock.install()
  let release, reads = 0
  await page.route('**/api/conversations/messages?*', async route => {
    reads++
    if (reads === 1) await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { items: [{ id: 'synthetic-message', agent_id: 7, agent_name: 'Synthetic agent', payload: { text: 'Synthetic arrived message' }, created_at: '2026-01-01T10:00:00Z',
      topic_id: null, round_id: null, channel_kind: 'matrix', room_id: 'Synthetic room' }], total: 1, page: 1, page_size: 50, summary: { idle: 1, ready: 0, running: 0, errors: 0 } } })
  })
  await mount(page, 'app/conversation/components/ConversationHistory.vue')
  try {
    await expect.poll(() => Boolean(release)).toBe(true)
    await page.clock.fastForward(10_000)
    expect(reads).toBe(1)
    release()
    await expect(page.getByText('Synthetic arrived message', { exact: true })).toBeVisible()
    await page.clock.fastForward(3_000)
    await expect.poll(() => reads).toBe(2)
  } finally { release?.() }
})

test('service parameters keep a reopened draft when a previous save completes and recover failed reads', async ({ page }) => {
  let release, fail = true
  const tool = { id: 91, code: 'synthetic', label: 'Synthetic Service', can_edit: true,
    connection_schema: { params: { endpoint: { type: 'string', required: false, label: 'Endpoint' } } }, global_params: {} }
  await page.route('**/api/services/91/global-params', async route => {
    if (route.request().method() === 'PUT') {
      expect(route.request().postDataJSON()).toEqual({ params: { endpoint: { value: 'First save', forced: false, clear: false } } })
      await new Promise(resolve => { release = resolve })
    }
    return route.fulfill(fail ? { status: 503, json: { detail: 'Synthetic parameters outage' } }
      : { json: { service_id: 91, params: { endpoint: { value: 'Saved endpoint', configured: true, forced: false } } } })
  })
  await mount(page, 'app/services/components/ServiceGlobalParameters.vue', { props: { modelValue: true, tool }, privileges: ['SERVICE_EDIT'] })
  const dialog = page.getByRole('dialog'), input = dialog.getByRole('textbox', { name: 'Endpoint', exact: true })
  await expect(dialog.getByRole('alert').filter({ hasText: 'Synthetic parameters outage' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  fail = false
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(input).toHaveValue('Saved endpoint')
  await input.fill('First save')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  try {
    await expect.poll(() => Boolean(release)).toBe(true)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await page.evaluate(() => window.testApp.setProps({ modelValue: true }))
    await expect(input).toHaveValue('Saved endpoint')
    await input.fill('Reopened draft')
    await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
    const response = page.waitForResponse(response => response.url().endsWith('/services/91/global-params') && response.request().method() === 'PUT')
    release(); await response
    await expect(dialog).toBeVisible()
    await expect(input).toHaveValue('Reopened draft')
    await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
  } finally { release?.() }
})
