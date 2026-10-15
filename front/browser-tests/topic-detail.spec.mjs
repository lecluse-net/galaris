import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document, result } from './data.mjs'

const at = '2026-09-01T12:00:00Z'
const task = { id: 'topic-task', label: 'Synthetic task', objective: '<p>Synthetic task objective</p>',
  status: 'SUCCESS', paused: false, agent_id: null, parent_id: null, topic_id: null, data: {},
  execution_result: result, revision: 1, created_at: at, updated_at: null, effort: 'standard', ai: true,
  cost: 0, messages: [] }
const round = { id: 'topic-round', agent_id: 7, agent_name: 'Synthetic agent', channel_kind: 'chat',
  connection_id: 1, room_id: 'topic-room', participant_key: 'synthetic', language: 'en', topic_id: null,
  status: 'COMPLETED', rendered_input: [{ text: 'Synthetic text input' }], response_text: 'Synthetic text answer',
  last_error: null, execution_result: result, delivery_state: 'DELIVERED', attempt_count: 1,
  created_at: at, finished_at: at, unknown_notifications: [] }
const turn = { id: 'topic-turn', session_id: 'topic-session', sequence: 1, status: 'COMPLETED',
  started_at: at, transcript: 'Synthetic audio input', assistant_response: 'Synthetic audio answer',
  topic_id: null, llm_call_count: 0, execution_result: null }
const room = { id: 'topic-room', agent_id: 7, agent_name: 'Synthetic agent', label: 'Synthetic space',
  external_id: 'synthetic-space', kind: 'chat', conversation_type: 'text', members: [] }
const content = {
  topic: { id: 'topic-a', title: 'Synthetic dossier', description: '', keywords: [], created_at: at },
  summary: { tasks: 1, conversation_rounds: 1, voice_turns: 1, rooms: 1, memories: 1, documents: 1 },
  tasks: [task], conversation_rounds: [{ ...round, room_label: 'Synthetic text round', preview: 'Text summary' }],
  voice_turns: [{ ...turn, room_label: 'Synthetic audio round', preview: 'Audio summary' }], rooms: [room],
  memories: [{ id: 'topic-memory', title: 'Synthetic memory', excerpt: 'Memory summary', owner_agent_id: null }],
  documents: [{ id: 'doc-a', title: 'Synthetic document', filename: null }],
}

async function openTopic(page, width = 1440) {
  await page.setViewportSize({ width, height: 900 })
  await jsonRoute(page, '**/api/topics/topic-a/content?*', content)
  await jsonRoute(page, '**/api/topics/refs?*', [])
  await mount(page, 'app/topic/pages/[id].vue', { privileges: ['TOPIC_ACCESS', 'TASK_ACCESS', 'MEMORY_ACCESS'] })
  await page.evaluate(async () => {
    window.testApp.router.addRoute({ path: '/topic/:id', component: { render: () => null } })
    await window.testApp.navigate('/topic/topic-a')
  })
  await expect(page.getByText('Synthetic dossier', { exact: true })).toBeVisible()
}

for (const width of [1440, 390]) test(`topic rows open their target dialogs without leaving the dossier at ${width}px`, async ({ page }, testInfo) => {
  await jsonRoute(page, '**/api/tasks/topic-task/full', task)
  await jsonRoute(page, '**/api/tasks/topic-task', task)
  await jsonRoute(page, '**/api/tasks/topic-task/children', [])
  await jsonRoute(page, '**/api/tasks/activity', [])
  await jsonRoute(page, '**/api/tasks/topic-task/budget', { enabled: false })
  await jsonRoute(page, '**/api/conversations/rounds/topic-round', round)
  await jsonRoute(page, '**/api/llm-calls?*', [])
  await jsonRoute(page, '**/api/voice/conversations/turns/topic-turn', turn)
  await page.route('**/api/voice/conversations/turns/topic-turn/deletion', route => route.fulfill({ status: 404, json: {} }))
  await jsonRoute(page, '**/api/voice/conversations/topic-session', {
    id: 'topic-session', agent_id: 7, agent_name: 'Synthetic agent', status: 'COMPLETED',
    transport_kind: 'chat', room_id: 'topic-room', language: 'en', turns: [turn],
  })
  await jsonRoute(page, '**/api/chat/rooms/topic-room', room)
  await jsonRoute(page, '**/api/chat/rooms/topic-room/speech/status', { available_agent_ids: [] })
  await jsonRoute(page, '**/api/chat/rooms/topic-room/messages?*', { items: [{ id: 'topic-message',
    room_id: room.id, text: 'Synthetic space message', sender: null, is_mine: false, files: [], created_at: at }],
    total: 1, history_has_more: false, history_next_cursor: null })
  await jsonRoute(page, '**/api/chat/rooms/topic-room/messages/topic-message/previews?*', [])
  await jsonRoute(page, '**/api/memory/items/topic-memory', {
    ...document, id: 'topic-memory', node_kind: 'memory', payload: { text: 'Synthetic memory body' },
  })
  await jsonRoute(page, '**/api/memory/documents/doc-a', { item: { ...document, title: 'Synthetic document' } })
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a/content/revisions?*', { items: [], total: 0 })
  await openTopic(page, width)
  const dialog = page.getByRole('dialog')
  await page.getByText('Synthetic task objective', { exact: true }).click()
  await expect(dialog.locator('.task-detail').getByText('Synthetic task', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('topic-task-dialog.png') })
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  for (const [tab, line, expected] of [
    ['Text rounds', 'Text summary', 'Synthetic text answer'],
    ['Voice rounds', 'Audio summary', 'Synthetic audio answer'],
    ['Spaces and resources', 'Synthetic space', 'Synthetic space message'],
    ['Spaces and resources', 'Memory summary', 'Synthetic memory body'],
    ['Spaces and resources', 'Synthetic document', 'Initial body'],
  ]) {
    await page.getByRole('tab', { name: tab, exact: true }).click()
    const row = page.locator('.q-item').filter({ hasText: line }).first()
    await row.focus()
    await page.keyboard.press('Enter')
    await expect(dialog.getByText(expected, { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`topic-${line.replaceAll(' ', '-')}-dialog.png`) })
    if (width === 390 && line === 'Synthetic document') {
      await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
    } else {
      await page.locator('.q-dialog__backdrop').last().click({ position: { x: 5, y: 5 } })
    }
    await expect(dialog).toHaveCount(0)
    expect(await page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/topic/topic-a')
  }
})

test('target dialogs recover denied reads and ignore replies after closing', async ({ page }) => {
  let release
  let releaseCalls
  const pending = new Promise(resolve => { release = resolve })
  const pendingCalls = new Promise(resolve => { releaseCalls = resolve })
  let callsWaiting = false
  let mode = 'denied'
  await page.route('**/api/conversations/rounds/topic-round', async route => {
    if (mode === 'denied') return route.fulfill({ status: 403, json: { detail: 'Synthetic denied read' } })
    if (mode === 'late') await pending
    await route.fulfill({ json: round })
  })
  await page.route('**/api/llm-calls?*', async route => {
    if (mode === 'ok') { callsWaiting = true; await pendingCalls }
    await route.fulfill({ json: [] })
  })
  await openTopic(page)
  await page.getByRole('tab', { name: 'Text rounds', exact: true }).click()
  await page.locator('.q-item').filter({ hasText: 'Text summary' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(/This item could not be loaded/)).toBeVisible()
  mode = 'ok'
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(() => callsWaiting).toBe(true)
  await expect(dialog.getByText('Synthetic text answer', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  releaseCalls()
  mode = 'late'
  const request = page.waitForRequest('**/api/conversations/rounds/topic-round')
  await page.locator('.q-item').filter({ hasText: 'Text summary' }).click()
  await request
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  const response = page.waitForResponse('**/api/conversations/rounds/topic-round')
  release()
  await response
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText('Synthetic dossier', { exact: true })).toBeVisible()
})
