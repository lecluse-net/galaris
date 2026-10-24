import { test, expect, mount, jsonRoute, editorHtml, setPrivileges } from './fixtures.mjs'
import { goal as goalFixture, result } from './data.mjs'

const id = '00000000-0000-4000-8000-000000000251'
const at = '2026-09-01T12:00:00Z'
const task = { id, label: 'Synthetic work item', objective: '<p>FULL TASK OBJECTIVE</p>', status: 'SUCCESS', paused: false,
  agent_id: null, parent_id: null, topic_id: null, data: {}, execution_result: result, revision: 1,
  created_at: at, updated_at: null, effort: 'standard', ai: true, cost: 0, assignments: [] }
const round = { id, agent_id: 7, agent_name: 'Synthetic agent', channel_kind: 'chat', connection_id: 1,
  room_id: id, participant_key: 'synthetic', language: 'en', topic_id: null, status: 'COMPLETED',
  rendered_input: [{ text: 'FULL ROUND REQUEST' }], response_text: 'FULL ROUND RESPONSE', last_error: null,
  execution_result: result, delivery_state: 'DELIVERED', attempt_count: 1, created_at: at, finished_at: at, unknown_notifications: [] }
const turn = { id, session_id: id, sequence: 1, agent_id: 7, agent_name: 'Synthetic agent', status: 'COMPLETED',
  started_at: at, transcript: 'FULL VOICE TRANSCRIPT', assistant_response: 'FULL VOICE RESPONSE', topic_id: null,
  transport_kind: 'chat', room_id: id, llm_call_count: 0, execution_result: null }
const session = { id, agent_id: 7, agent_name: 'Synthetic agent', status: 'COMPLETED', transport_kind: 'chat',
  room_id: id, language: 'en', started_at: at, turn_count: 1, turns: [turn] }
const room = { id, agent_id: 7, agent_name: 'Synthetic agent', label: 'Synthetic discussion', external_id: 'synthetic',
  kind: 'chat', conversation_type: 'text', messenger_label: 'Chat', members: [], last_message: null }
const topic = { id, title: 'Synthetic dossier', description: 'A reusable dossier', keywords: ['Synthetic keyword'], created_at: at, revision: 1 }
const goal = { ...goalFixture, id, description: '<p>FULL GOAL DESCRIPTION</p>' }

async function fixtures(page) {
  await jsonRoute(page, `**/api/tasks/${id}`, task)
  await jsonRoute(page, `**/api/tasks/${id}/full`, task)
  await jsonRoute(page, `**/api/tasks/${id}/children`, [])
  await jsonRoute(page, `**/api/tasks/${id}/budget`, { enabled: false })
  await jsonRoute(page, '**/api/tasks/activity', [])
  await jsonRoute(page, `**/api/conversations/rounds/${id}`, round)
  await jsonRoute(page, '**/api/llm-calls?*', [])
  await jsonRoute(page, `**/api/voice/conversations/turns/${id}`, turn)
  await page.route(`**/api/voice/conversations/turns/${id}/deletion`, route => route.fulfill({ status: 404, json: {} }))
  await jsonRoute(page, `**/api/voice/conversations/${id}`, session)
  await jsonRoute(page, `**/api/chat/rooms/${id}`, room)
  await jsonRoute(page, `**/api/chat/rooms/${id}/speech/status`, { available_agent_ids: [] })
  await jsonRoute(page, `**/api/chat/rooms/${id}/messages?*`, { items: [], total: 0, history_has_more: false, history_next_cursor: null })
  await jsonRoute(page, `**/api/topics/${id}`, topic)
  await jsonRoute(page, `**/api/topics/${id}/content?*`, { topic, summary: { tasks: 0, conversation_rounds: 0, voice_turns: 0, rooms: 0, memories: 0, documents: 0 },
    tasks: [], conversation_rounds: [], voice_turns: [], rooms: [], memories: [], documents: [] })
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/agents/titles?*', [])
  await jsonRoute(page, '**/api/goals/settings', { globally_paused: false, schedule_enabled: false, schedule: [], timezone: 'UTC', is_active: true })
  await jsonRoute(page, '**/api/goals/runtime-status', { globally_paused: false, schedule_enabled: false, timezone: 'UTC', is_active: true })
  await jsonRoute(page, '**/api/goals/tree', { items: [goal], total: 1 })
  await jsonRoute(page, `**/api/goals/${id}/cycles?*`, { items: [], total: 0, page: 1, page_size: 50 })
  await jsonRoute(page, `**/api/goals/${id}`, goal)
}
test('a direct Task dialog survives query normalization and follows navigation and dismissal', async ({ page }) => {
  await fixtures(page)
  await jsonRoute(page, '**/api/tasks/recent?*', { items: [], total: 0,
    summary: { completed: 0, paused: 0, running: 0, errors: 0 } })
  await mount(page, 'app/task/pages/index.vue', {
    route: `/task?tab=tasks&task_id=${id}`, privileges: ['TASK_ACCESS'],
  })
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('FULL TASK OBJECTIVE')
  // Rewriting the activity query must not dismiss an unchanged Task reference.
  await page.evaluate(value => window.testApp.navigate(value), `/task?task_id=${id}`)
  await dialog.evaluate(element => Promise.all(element.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => {}))))
  await expect(dialog).toBeVisible()
  await page.evaluate(() => window.testApp.navigate('/task?tab=tasks'))
  await expect(dialog).toHaveCount(0)
  await page.evaluate(value => window.testApp.navigate(value), `/task?tab=tasks&task_id=${id}`)
  await expect(dialog).toContainText('FULL TASK OBJECTIVE')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await page.evaluate(() => window.testApp.navigate('/task?tab=tasks'))
  await page.evaluate(value => window.testApp.navigate(value), `/task?tab=tasks&task_id=${id}`)
  await expect(dialog).toBeVisible()
  await page.locator('.q-dialog__backdrop').last().click({ position: { x: 4, y: 4 } })
  await expect(dialog).toHaveCount(0)
  await page.evaluate(() => window.testApp.navigate('/task?tab=tasks'))
  await page.evaluate(value => window.testApp.navigate(value), `/task?tab=tasks&task_id=${id}`)
  await expect(dialog).toBeVisible()
  await setPrivileges(page, [])
  await expect(dialog).toHaveCount(0)
})

async function paste(page, text) {
  await page.locator('[data-editor-surface]').evaluate((root, value) => {
    const data = new DataTransfer(); data.setData('text/plain', value)
    root.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
  }, text)
}
const cases = [
  ['task', `/task?task_id=${id}`, task.label, 'FULL TASK OBJECTIVE'],
  ['goal', `/goal?goal_id=${id}`, goal.title, 'FULL GOAL DESCRIPTION'],
  ['topic', `/topic/${id}`, topic.title, 'A reusable dossier'],
  ['text', `/task?round_id=${id}`, 'Text conversation round', 'FULL ROUND RESPONSE'],
  ['voice', `/task?voice_turn_id=${id}`, 'Round #1', 'FULL VOICE RESPONSE'],
  ['voice_session', `/task?voice_session_id=${id}`, '1 conversation round', 'Synthetic agent'],
  ['room', `/chat?room=${id}`, room.label, 'No messages in this conversation yet.'],
]

for (const [kind, url, title, detail] of cases) for (const format of ['uri', 'url']) {
  test(`${kind} ${format} becomes a reversible compact card and reopens its modal`, async ({ page, context }, testInfo) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await fixtures(page)
    const uri = `galaris://${kind}/${id}`
    const grants = { task: 'TASK_ACCESS', goal: 'GOAL_ACCESS', topic: 'TOPIC_ACCESS',
      text: 'CONVERSATION_ACCESS', voice: 'VOICE_HISTORY_ACCESS', voice_session: 'VOICE_HISTORY_ACCESS', room: 'CHAT_ACCESS' }
    await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<p>Keep surrounding text</p>', profile: 'document' }, privileges: [grants[kind]] })
    const surface = page.locator('[data-editor-surface]')
    await surface.click(); await page.keyboard.press('End')
    if (format === 'uri') await paste(page, uri)
    else {
      await page.evaluate(value => navigator.clipboard.writeText(value), new URL(url, page.url()).href)
      await surface.locator('p').click({ button: 'right' })
      await page.getByRole('menuitem', { name: 'Paste', exact: true }).click()
    }
    const link = surface.locator('a')
    await expect(link).toContainText(title)
    await link.click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Show card', exact: true }).click()
    const card = surface.locator('blockquote.galaris-link-card')
    await expect(card).toContainText(title)
    if (['task', 'text', 'voice'].includes(kind)) await expect(card).not.toContainText(/FULL /)
    const stored = await editorHtml(page)
    expect(stored).toContain(uri)
    expect(stored).toContain('Keep surrounding text')
    expect(stored).not.toMatch(/<button|blob:/)
    await card.locator('p').nth(1).click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Show URL', exact: true }).click()
    await expect(card).toHaveCount(0)
    await surface.locator('a').click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Show card', exact: true }).click()
    expect(await editorHtml(page)).toBe(stored)
    await card.click({ position: { x: 4, y: 4 } })
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    if (kind !== 'room') await expect(dialog).toContainText(detail)
    if (kind === 'room') {
      // Discussions expose reference copying on the card, without a modal copy button.
      await page.keyboard.press('Escape')
      await card.click({ button: 'right', position: { x: 4, y: 4 } })
      await page.getByRole('menuitem', { name: 'Copy reference', exact: true }).click()
    } else if (kind === 'task') {
      await dialog.locator('.task-detail').click({ button: 'right' })
      await page.getByRole('menuitem', { name: 'Copy reference', exact: true }).click()
    } else await dialog.getByRole('button', { name: 'Copy reference', exact: true }).first().click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(uri)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await card.locator('a').click()
    await expect(dialog).toBeVisible()
    await page.locator('.q-dialog__backdrop').last().click({ position: { x: 4, y: 4 } })
    await expect(dialog).toHaveCount(0)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.testApp.dark(true))
    await card.screenshot({ path: testInfo.outputPath('compact-card-dark-mobile.png') })
    // A stored card works in the independent reader, with no navigation or editor mutation.
    await mount(page, 'core/util/components/RichText.vue', { props: { content: stored, profile: 'document' }, privileges: ['TASK_ACCESS', 'TOPIC_ACCESS'] })
    const before = page.url()
    await page.locator('.galaris-link-card').click({ button: 'right' })
    await expect(page.getByRole('menu')).toBeHidden()
    await page.locator('.galaris-link-card').click({ position: { x: 4, y: 4 } })
    await expect(page.getByRole('dialog')).toBeVisible()
    expect(page.url()).toBe(before)
  })
}

for (const mode of ['denied', 'late']) test(`business reference lookup handles ${mode} without changing another document`, async ({ page }) => {
  let release, started = false
  const gate = new Promise(resolve => { release = resolve })
  await page.route(`**/api/topics/${id}`, async route => {
    started = true; await gate
    await route.fulfill(mode === 'denied' ? { status: 403, json: { detail: 'Denied' } } : { json: topic })
  })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<p>Keep original</p>', profile: 'document' } })
  await page.locator('[data-editor-surface]').click()
  await paste(page, `galaris://topic/${id}`)
  await expect.poll(() => started).toBe(true)
  if (mode === 'late') await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Replacement document</p>' }))
  const response = page.waitForResponse(`**/api/topics/${id}`)
  release(); await response
  if (mode === 'late') await expect(page.locator('[data-editor-surface]')).toHaveText('Replacement document')
  else await expect(page.locator('[data-editor-surface] a')).toHaveText(`galaris://topic/${id}`)
})

async function searchFixtures(page, failure = false) {
  for (const [path, value] of [
    ['tasks/recent', { items: [task] }], ['goals', { items: [goal] }], ['topics', { items: [topic] }],
    ['conversations/messages', { items: [{ ...round, round_id: id }] }], ['voice/conversations', { items: [session] }],
    ['chat/rooms', { items: [room] }],
  ]) await page.route(`**/api/${path}?*`, route => route.fulfill(failure ? { status: 503, json: { detail: 'Unavailable' } } : { json: value }))
}

test('the editor object picker inserts titled references, retries failures and preserves selected formatting', async ({ page }) => {
  await fixtures(page)
  await searchFixtures(page, true)
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [])
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<p><strong>Selected phrase</strong></p>', profile: 'document', resourceAgentId: 7 } })
  await page.locator('[data-editor-surface]').click(); await page.keyboard.press('Control+a')
  await page.getByRole('button', { name: 'Galaris link', exact: true }).click()
  await page.getByRole('tab', { name: 'Galaris objects', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('alert')).toBeVisible()
  await searchFixtures(page)
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await dialog.getByText(topic.title, { exact: true }).click()
  await expect(dialog).toHaveCount(0)
  const html = await editorHtml(page)
  expect(html).toContain(`href="galaris://topic/${id}"`)
  expect(html).toContain('Selected phrase')
  expect(html).toContain('<strong>')
  await page.keyboard.press('Control+z')
  await expect(page.locator('[data-editor-surface] a')).toHaveCount(0)
})

test('the activity task menu copies a reference usable in a document', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await mount(page, 'app/task/components/ActiveTaskNode.vue', { props: { task } })
  await page.locator('.active-task-row').click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Copy reference', exact: true }).click()
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(`galaris://task/${id}`)
})

test('an object remains selectable while a debounced search starts during the click', async ({ page }) => {
  await searchFixtures(page)
  let release, started = false
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/topics?*', async route => {
    if (new URL(route.request().url()).searchParams.get('q') === 'another search') { started = true; await gate }
    await route.fulfill({ json: { items: [topic] } })
  })
  await mount(page, 'BusinessReferencePicker.vue', { containerStyle: { height: '100vh', display: 'flex', flexDirection: 'column' } })
  const item = page.getByRole('button').filter({ has: page.getByText(topic.title, { exact: true }) })
  await expect(item).toBeVisible()
  const bounds = await item.boundingBox()
  await page.getByRole('textbox', { name: 'Search Galaris objects', exact: true }).fill('another search')
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
  await page.mouse.down()
  await expect.poll(() => started).toBe(true)
  await page.mouse.up()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'select').map(event => event.value.uri))).toEqual([`galaris://topic/${id}`])
  release()
})
