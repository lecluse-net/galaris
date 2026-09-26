import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { result, call } from './data.mjs'

const task = index => ({ id: `task-${index}`, label: `Task ${index}`, objective: `Objective ${index}`, status: 'SUCCESS', paused: false, agent_id: null, tree_parent_id: null, parent_id: null, directly_linked: true, topic_id: null, data: {}, execution_result: result, revision: 1, created_at: `2026-09-01T12:${String(index % 60).padStart(2, '0')}:00Z`, updated_at: null })

async function panel(page, items, total = items.length, activity = []) {
  const requests = []
  await page.route('**/api/tasks/activity', route => route.fulfill({ json: activity }))
  await jsonRoute(page, '**/api/chat/recipients?*', { agents: [], users: [] })
  await page.route('**/api/chat/rooms/room-a/tasks?*', route => {
    requests.push(new URL(route.request().url()).searchParams)
    return route.fulfill({ json: { items, total, page: 1, page_size: 10 } })
  })
  await mount(page, 'app/chat/components/AgentTasksPanel.vue', {
    props: { roomId: 'room-a', fromMessageId: 'message-a', canRead: true },
    containerStyle: { height: '180px', display: 'flex', flexDirection: 'column' },
  })
  await expect(page.locator('.agent-task-row')).toHaveCount(items.length)
  return requests
}
const scrolling = page => page.locator('.agent-tasks-scroll .q-scrollarea__container')
const bottomGap = page => scrolling(page).evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)

test('completed task expansion is local to the row and does not open task details', async ({ page }) => {
  await panel(page, [task(1), task(2)])
  const toggles = page.locator('.agent-task-expansion-toggle')
  await expect(toggles.nth(0)).toHaveAttribute('aria-expanded', 'false')
  await expect(toggles.nth(1)).toHaveAttribute('aria-expanded', 'false')
  await toggles.nth(0).click()
  await expect(toggles.nth(0)).toHaveAttribute('aria-expanded', 'true')
  await expect(toggles.nth(1)).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByText('Objective 1', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('agent work loads without messages, refreshes and follows the selected conversation', async ({ page }) => {
  const items = [{ ...task(1), status: 'EXEC', directly_linked: false }]
  const requests = await panel(page, items)
  await page.evaluate(() => window.testApp.setProps({ fromMessageId: null }))
  await expect.poll(() => requests.at(-1)?.has('from_message_id')).toBe(false)
  await expect(page.getByText('Task 1', { exact: true })).toBeVisible()
  items.splice(0)
  await page.evaluate(() => window.testApp.emitSocket('task.update', { data: { id: 'task-1', status: 'SUCCESS' } }))
  await expect(page.locator('.agent-task-row')).toHaveCount(0)
  await jsonRoute(page, '**/api/chat/rooms/room-b/tasks?*', { items: [task(2)], total: 1, page: 1, page_size: 10 })
  await page.evaluate(() => window.testApp.setProps({ roomId: 'room-b' }))
  await expect(page.getByText('Task 2', { exact: true })).toBeVisible()
  await expect(page.getByText('Task 1', { exact: true })).toHaveCount(0)
})

const activityFor = (task, streams = true) => ({
  task_id: task.id, revision: task.revision, run_id: 'run', streams_ai_messages: streams,
  operational: { operational_state: 'RUNNING', resume_phase: 'EXEC', waits: [] },
  pause_pending: false, attempt_number: 1, live: null,
})

test('Task previews display complete messages without streaming, including after reconnect', async ({ page }) => {
  const item = { ...task(1), status: 'EXEC', execution_result: undefined,
    data: {} }
  const snapshot = activityFor(item)
  // HTTP checkpoints include nulls; live events omit them (exclude_none=True).
  snapshot.live = { run_id: 'run', sequence: 3, result: { ...result, messages: [
    { type: 'tool', tool_name: 'search', content: 'Ready' },
    { type: 'text', stream_id: 'text', tool_name: null, stream_complete: false, content: 'Hello' },
  ] } }
  const activities = [snapshot]
  await panel(page, [item], 1, activities)
  await expect(page.locator('.agent-task-operations')).toContainText('Ready')
  const event = { task_id: item.id, run_id: 'run', sequence: 4, kind: 'message', message: { type: 'text', stream_id: 'text', stream_complete: false, content: ' world' } }
  await page.evaluate(async data => {
    await window.testApp.emitSocket('agent_run.event', { data })
    await window.testApp.emitSocket('agent_run.event', { data })
  }, event)
  await expect(page.locator('.compact-operation--stream-tail')).toHaveCount(0)
  await page.evaluate(data => window.testApp.emitSocket('agent_run.event', { data }),
    { ...event, sequence: 5, message: { ...event.message, content: '!', stream_complete: true } })
  await expect(page.locator('.compact-operation--stream-tail')).toHaveCount(1)
  await expect(page.locator('.compact-operation--stream-tail')).toContainText('Hello world!')
  snapshot.live = { run_id: 'run', sequence: 6, result: { ...result, messages: [{ type: 'text', stream_id: 'text', tool_name: null, stream_complete: false, content: 'Recovered progress' }] } }
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect(page.locator('.compact-operation--stream-tail')).toHaveCount(0)
  await page.evaluate(data => window.testApp.emitSocket('agent_run.event', { data }),
    { ...event, sequence: 7, message: { ...event.message, content: ', continued', stream_complete: true } })
  await expect(page.locator('.compact-operation--stream-tail')).toHaveCount(1)
  await expect(page.locator('.compact-operation--stream-tail')).toContainText('Recovered progress, continued')
  // Resume the same run with a new attempt and a sequence lower than the old one.
  snapshot.latest_attempt = { id: 'attempt-2', attempt_number: 2, phase: 'EXEC', status: 'CLAIMED' }
  snapshot.live = { run_id: 'run', attempt_id: 'attempt-2', sequence: 1,
    result: { ...result, messages: [{ type: 'text', content: 'Resumed progress', stream_id: 'resumed', stream_complete: true }] } }
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect(page.locator('.agent-task-operations')).toContainText('Resumed progress')
  await page.evaluate(data => window.testApp.emitSocket('agent_run.event', { data }),
    { task_id: item.id, run_id: 'run', attempt_id: 'attempt-1', sequence: 999, kind: 'message', message: { type: 'text', content: 'Obsolete attempt' } })
  await expect(page.locator('.agent-task-operations')).not.toContainText('Obsolete attempt')
})

test('custom Harness uses only correlated calls and replaces updates and deleted calls', async ({ page }) => {
  const item = { ...task(1), status: 'EXEC', execution_result: undefined,
    data: { _agent_run_identity: { request_run_id: 'run' } } }
  const calls = [{ ...call, task_id: item.id, agent_run_id: 'run', response_text: 'First response' },
    { ...call, id: 'foreign', task_id: item.id, agent_run_id: 'previous', response_text: 'Private previous run' }]
  await page.route('**/api/llm-calls?*', route => route.fulfill({ json: calls }))
  await panel(page, [item], 1, [activityFor(item, false)])
  const operations = page.locator('.agent-task-operations')
  await expect(operations).toContainText('First response')
  await expect(operations).not.toContainText('Private previous run')
  await page.evaluate(data => window.testApp.emitSocket('agent_run.event', { data }),
    { task_id: item.id, run_id: 'run', sequence: 1, kind: 'message', message: { type: 'text', content: 'Native text must stay separate' } })
  await expect(operations).not.toContainText('Native text')
  calls[0].response_text = 'Updated response'
  await page.evaluate(data => window.testApp.emitSocket('llm_call.update', { data }), calls[0])
  await expect(operations).toContainText('Updated response')
  await expect(operations).not.toContainText('First response')
  calls[0] = { ...calls[0], status: 'running', completed_at: null, response_text: 'Unfinished response' }
  await page.evaluate(data => window.testApp.emitSocket('llm_call.update', { data }), calls[0])
  await expect(page.locator('.agent-task-row')).not.toContainText('Updated response')
  await expect(page.locator('.agent-task-row')).not.toContainText('Unfinished response')
  calls.splice(0, 1)
  await page.evaluate(() => window.testApp.emitSocket('llm_call.delete', { data: { id: 'call-1', task_id: 'task-1' } }))
  await expect(page.getByText('Updated response', { exact: true })).toHaveCount(0)
})

test('waiting task explains its dependency and stops suggesting active work', async ({ page }) => {
  const item = { ...task(1), status: 'EXEC', execution_result: { ...result, messages: [{ type: 'tool', tool_name: 'search', content: 'Ready' }] } }
  const snapshot = activityFor(item)
  snapshot.operational = { operational_state: 'WAITING', resume_phase: 'EXEC', waits: [{ kind: 'HUMAN_REPLY', peer_display: 'Alice', question: 'Which period?' }] }
  await panel(page, [item], 1, [snapshot])
  await expect(page.getByRole('status').filter({ hasText: 'Which period?' })).toBeVisible()
  await expect(page.locator('.compact-operation-spinner')).toHaveCount(0)
})

test('task details restore activity and expose the admitted demand and recorded delivery receipt', async ({ page }) => {
  const item = { ...task(1), status: 'EXEC', data: { _agent_run_identity: { request_run_id: 'run' } },
    execution_result: undefined, effort: 'standard', ai: true, cost: 0, messages: [] }
  const snapshot = { ...activityFor(item), phase: 'EXEC', pause_pending: true,
    operational: { operational_state: 'PAUSED', resume_phase: 'EXEC', waits: [] },
    original_demand: 'The original report request',
    resources: [{ type: 'delivery_receipt', reference: 'receipt://report-1', label: 'Delivered report', state: 'active', producer_task_id: item.id }],
    live: { run_id: 'run', sequence: 2, result: { ...result, success: false, messages: [{ type: 'text', content: 'Recovered detail activity', stream_id: 'text', stream_complete: true }] } } }
  await jsonRoute(page, '**/api/tasks/task-1/full', item)
  await jsonRoute(page, '**/api/tasks/task-1', item)
  await jsonRoute(page, '**/api/tasks/task-1/children', [])
  await jsonRoute(page, '**/api/tasks/activity', [snapshot])
  await jsonRoute(page, '**/api/tasks/task-1/budget', {
    enabled: false, scope: 'task_tree', provider_hard_cap: false,
    recorded_tokens: 123, recorded_cost: 0.25, active_phases: 0,
    reserved_tokens: 0, reserved_cost: 0,
    remaining_tokens: null, remaining_cost: null, remaining_seconds: null,
  })
  await jsonRoute(page, '**/api/topics?*', [])
  await mount(page, 'app/task/components/TaskDetail.vue', { props: { taskId: item.id } })
  await expect(page.getByRole('paragraph').filter({ hasText: 'Recovered detail activity' })).toBeVisible()
  await expect(page.getByText('Failure', { exact: true })).toHaveCount(0)
  await page.getByRole('tab', { name: 'Details', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Pause requested' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Usage and budgets', exact: true })).toContainText('123 tokens · $0.2500')
  await page.locator('summary').filter({ hasText: 'Request and deliveries' }).click()
  await expect(page.getByText('Original request : The original report request', { exact: true })).toBeVisible()
  await expect(page.getByText('receipt://report-1', { exact: true })).toBeVisible()
})

test('task panel starts at the latest work and preserves the reading position on updates', async ({ page }) => {
  const items = Array.from({ length: 10 }, (_, index) => task(index))
  const requests = await panel(page, items)
  expect(requests[0].get('page_size')).toBe('10')
  await expect.poll(() => bottomGap(page)).toBeLessThan(3)
  await scrolling(page).hover()
  await page.mouse.wheel(0, -180)
  await expect.poll(() => bottomGap(page)).toBeGreaterThan(100)
  const before = await scrolling(page).evaluate(node => node.scrollTop)
  items[0] = { ...items[0], label: 'Updated task', revision: 2 }
  await page.evaluate(item => window.testApp.emitSocket('task.update', { data: item }), items[0])
  await expect.poll(() => requests.length).toBeGreaterThan(1)
  await expect.poll(() => scrolling(page).evaluate((node, position) => Math.abs(node.scrollTop - position), before)).toBeLessThan(3)
  const toolbar = page.locator('.agent-tasks-toolbar')
  await expect(toolbar).toBeInViewport()
  await page.locator('.scroll-to-bottom-button').click()
  await expect.poll(() => bottomGap(page)).toBeLessThan(3)
})

test('suspended task operations stop animation and preserve tool names and streamed tail', async ({ page }) => {
  const executionResult = { ...result, messages: [{ type: 'tool', tool_name: 'search_docs', content: 'Result' }, { type: 'text', content: `Old text ${'word '.repeat(100)}Current tail` }] }
  await mount(page, 'app/chat/components/CompactTaskOperations.vue', { props: { executionResult, status: 'EXEC', paused: false } })
  await expect(page.locator('.compact-operation-spinner')).toHaveCount(1)
  await expect(page.locator('.compact-operation--tool')).toContainText('search_docs')
  await expect(page.locator('.compact-operation--stream-tail')).toContainText('Current tail')
  await expect(page.locator('.compact-operation--stream-tail')).not.toContainText('Old text')
  await page.evaluate(() => window.testApp.setProps({ paused: true }))
  await expect(page.locator('.compact-operation-spinner')).toHaveCount(0)
})
