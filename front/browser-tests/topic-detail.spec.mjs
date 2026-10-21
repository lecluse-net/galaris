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
  summary: { tasks: 1, conversation_rounds: 1, voice_turns: 1, rooms: 1, memories: 1, documents: 1, datasets: 1 },
  tasks: [task], conversation_rounds: [{ ...round, room_label: 'Synthetic text round', preview: 'Text summary' }],
  voice_turns: [{ ...turn, room_label: 'Synthetic audio round', preview: 'Audio summary' }], rooms: [room],
  memories: [{ id: 'topic-memory', title: 'Synthetic memory', excerpt: 'Memory summary', owner_agent_id: null }],
  documents: [{ id: 'doc-a', title: 'Synthetic document', filename: null }],
  datasets: [{ id: 'topic-dataset', title: 'Synthetic linked Dataset' }],
}

async function openTopic(page, width = 1440) {
  await page.setViewportSize({ width, height: 900 })
  await jsonRoute(page, '**/api/topics/topic-a/content?*', content)
  await jsonRoute(page, '**/api/topics/refs?*', [])
  await mount(page, 'app/topic/pages/[id].vue', { privileges: ['TOPIC_ACCESS', 'TASK_ACCESS', 'MEMORY_ACCESS', 'DATASET_READ'] })
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
  await jsonRoute(page, '**/api/memory/documents/keywords', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a/content/revisions?*', { items: [], total: 0 })
  await jsonRoute(page, '**/api/datasets/topic-dataset', { id: 'topic-dataset', uri: 'data://topic-dataset',
    title: 'Synthetic linked Dataset', content: '{"quantity":3}', revision: 1, lock_version: 1,
    can_write: false, can_manage: false, can_delete: false, keywords: [], read_only: false,
    global_access: 0, group_access: 0, owner_agent_id: null, owner_user_id: null })
  await jsonRoute(page, '**/api/datasets/topic-dataset/owner', { owner: null, options: [] })
  await jsonRoute(page, '**/api/datasets/topic-dataset/sharing', { lock_version: 1, can_manage: false,
    level: 'private', grants: [], options: [], owner: null, owner_groups: [] })
  await openTopic(page, width)
  const dialog = page.getByRole('dialog')
  await page.getByRole('tab', { name: 'Tasks', exact: true }).click()
  await page.getByText('Synthetic task objective', { exact: true }).click()
  await expect(dialog.locator('.task-detail').getByText('Synthetic task', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('topic-task-dialog.png') })
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  for (const [tab, line, expected] of [
    ['Linked content', 'Synthetic space', 'Synthetic space message'],
    ['Memories', 'Memory summary', 'Synthetic memory body'],
    ['Linked content', 'Synthetic document', 'Initial body'],
  ]) {
    await page.getByRole('tab', { name: tab, exact: true }).click()
    const row = page.locator('.q-item').filter({ hasText: line }).first()
    await row.focus()
    await page.keyboard.press('Enter')
    await expect(dialog.getByText(expected, { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`topic-${line.replaceAll(' ', '-')}-dialog.png`) })
    // Mobile details may fill the viewport and leave no exposed backdrop. The
    // accessible close action remains usable; desktop still exercises dismissal.
    if (width === 390) {
      await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
    } else {
      await page.locator('.q-dialog__backdrop').last().click({ position: { x: 5, y: 5 } })
    }
    await expect(dialog).toHaveCount(0)
    expect(await page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/topic/topic-a')
  }
  await page.getByText('Synthetic linked Dataset', { exact: true }).click()
  await expect(dialog.getByRole('textbox', { name: 'JSON content', exact: true })).toHaveValue('{\n  "quantity": 3\n}')
  await page.screenshot({ path: testInfo.outputPath('topic-dataset-dialog.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText('Synthetic linked Dataset', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/topic/topic-a')
})

test('memory details recover denied reads and ignore replies after closing', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  let mode = 'denied'
  await page.route('**/api/memory/items/topic-memory', async route => {
    if (mode === 'denied') return route.fulfill({ status: 403, json: { detail: 'Synthetic denied read' } })
    if (mode === 'late') await pending
    await route.fulfill({ json: {
      ...document, id: 'topic-memory', node_kind: 'memory', payload: { text: 'Synthetic memory body' },
    } })
  })
  await openTopic(page)
  await page.getByRole('tab', { name: 'Memories', exact: true }).click()
  await page.locator('.q-item').filter({ hasText: 'Memory summary' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(/This item could not be loaded/)).toBeVisible()
  mode = 'ok'
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByText('Synthetic memory body', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  mode = 'late'
  const request = page.waitForRequest('**/api/memory/items/topic-memory')
  await page.locator('.q-item').filter({ hasText: 'Memory summary' }).click()
  await request
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  const response = page.waitForResponse('**/api/memory/items/topic-memory')
  release()
  await response
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText('Synthetic dossier', { exact: true })).toBeVisible()
})
