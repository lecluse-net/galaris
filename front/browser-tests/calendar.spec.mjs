import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'
import { agent, document, goal, result } from './data.mjs'

const id = '00000000-0000-0000-0000-000000000091'
const taskId = '00000000-0000-0000-0000-000000000092'
const reviewTaskId = '00000000-0000-0000-0000-000000000094'
const feed = { id: 9, connection_id: 42, agent_id: 7, label: 'Synthetic agenda', tool_label: 'Synthetic Calendar', source_kind: 'internal', timezone: 'Europe/Paris', is_default: true, active: true, writable: true, initialized: true, actions_enabled: true, last_synced_at: null, last_error: null }
const event = { event_id: id, occurrence_id: id, recurrence_key: '20261112T090000Z', revision: 1, recurring: false, sync_state: 'local', calendar_id: 9, calendar_label: feed.label, uid: 'synthetic-event@example.test', summary: 'Prepare synthetic review', description: 'Synthetic event content', location: 'Meeting room', start: '2026-11-12T09:00:00Z', end: '2026-11-12T10:00:00Z', all_day: false, start_date: null, end_date: null, timezone_name: 'Europe/Paris', status: '', transparent: false }
const detail = { ...event, timezone: 'Europe/Paris', deleted: false, rrule: null, rdates: [], exdates: [], alarms: [], ical: 'BEGIN:VCALENDAR\nEND:VCALENDAR' }
const execution = { id: '00000000-0000-0000-0000-000000000093', calendar_id: 9, calendar_label: feed.label, event_id: id, recurrence_key: event.recurrence_key, action_key: 'synthetic-action', event_summary: event.summary, reminder_at: event.start, task_uri: `galaris://task/${taskId}`, state: 'done', task_status: 'SUCCESS', dispatch_status: 'submitted', treated: true }
const syncProgress = (changes = {}) => ({ calendar_changed: false, steps: [], server_reached: false, network_phase: null,
  http_requests: 0, last_http_status: null, calendars: 0, downloaded: 0, download_total: null, applied: 0, apply_total: null,
  uploaded: 0, upload_total: null, upload_succeeded: 0, conflicts: 0, deleted: 0, bytes_received: 0, bytes_sent: 0,
  transfer_completed: 0, transfer_total: null, ...changes })

async function calendar(page, changes = {}) {
  const model = { feeds: [{ ...feed }], events: [{ ...event }], detail: { ...detail }, actions: [], executions: [{ ...execution }], writes: [], queries: [], stateReads: [], ...changes }
  await jsonRoute(page, '**/api/calendars/connection-options', [{ id: 42, agent_id: 7, label: 'Alice Example' }])
  await jsonRoute(page, '**/api/calendars/9/sync-runs?*', [])
  await page.route('**/api/calendars?*', route => route.fulfill({ json: model.feeds }))
  await page.route('**/api/calendars/events?*', route => {
    const url = new URL(route.request().url()); model.queries.push(url)
    return route.fulfill({ json: { items: model.events.filter(row => row.start < url.searchParams.get('end') && row.end > url.searchParams.get('start') && url.searchParams.getAll('calendar_ids').includes(String(row.calendar_id))), total: model.events.length, complete: true, stale_calendar_ids: [] } })
  })
  await page.route('**/api/calendars/execution-states', route => {
    const body = route.request().postDataJSON(); model.stateReads.push(body)
    return route.fulfill({ json: body.occurrences.map(row => ({ ...row, total: 1, states: { done: 1 } })) })
  })
  await page.route('**/api/calendars/9/events', route => {
    const body = route.request().postDataJSON(); model.writes.push({ method: 'create', body })
    if (model.createFailure) return route.fulfill({ status: 503, json: { detail: 'Synthetic event save failure' } })
    const row = { ...event, ...body, all_day: body.start.length === 10, start_date: body.start.length === 10 ? body.start : null, end_date: body.start.length === 10 ? body.end : null }
    model.detail = { ...detail, ...row, recurring: Boolean(body.rrule) }; model.events = [row]
    return route.fulfill({ json: { event_id: id, calendar_id: 9, uid: row.uid, revision: 1, sync_state: 'local', state: 'created' } })
  })
  await page.route(new RegExp(`/api/calendars/9/events/${id}(?:\\?.*)?$`), route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: !new URL(route.request().url()).searchParams.has('recurrence_key') && model.master ? model.master : model.detail })
    const body = route.request().postDataJSON(); model.writes.push({ method: route.request().method(), body })
    if (model.writeFailure) return route.fulfill({ status: model.writeFailure, json: { detail: 'Synthetic concurrent edit' } })
    model.detail = { ...model.detail, ...body, revision: model.detail.revision + 1 }
    if (route.request().method() === 'DELETE') model.events = []
    else model.events = model.events.map(row => row.event_id === id ? { ...row, ...body, revision: model.detail.revision } : row)
    return route.fulfill({ json: { event_id: id, calendar_id: 9, uid: event.uid, revision: model.detail.revision, sync_state: 'local', state: 'updated' } })
  })
  await page.route(`**/api/calendars/9/events/${id}/actions**`, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: model.actions })
    const body = route.request().postDataJSON(); model.writes.push({ method: 'action', body })
    if (model.actionFailure) return route.fulfill({ status: 503, json: { detail: 'Synthetic launch save failure' } })
    const action = { ...body, id: 'synthetic-action', event_id: id, revision: 1 }; model.actions = [action]
    return route.fulfill({ json: action })
  })
  await page.route('**/api/calendars/reminders?*', route => route.fulfill({ json: { items: model.executions, total: model.executions.length } }))
  await page.route('**/api/calendars/9/executions/*/relaunch', route => {
    model.writes.push({ method: 'relaunch', body: route.request().postDataJSON() }); return route.fulfill({ json: { id: 'synthetic-relaunch', state: 'scheduled', task_uri: null } })
  })
  await page.route('**/api/calendars/9', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: model.feeds.find(row => row.id === 9) })
    const body = route.request().postDataJSON(); model.writes.push({ method: 'settings', body }); model.feeds[0] = { ...model.feeds[0], ...body }; return route.fulfill({ json: model.feeds[0] })
  })
  await jsonRoute(page, `**/api/calendars/9/events/${id}/history*`, [{ revision: 1, deleted: false, created_at: event.start, ical: detail.ical }])
  return model
}
async function start(page, options = {}) {
  await mount(page, 'app/calendar/pages/index.vue', { route: '/calendar?agent_id=7&date=2026-11-12&view=month&timezone=Europe%2FParis', privileges: ['CALENDAR_EDIT', 'TASK_ACCESS'], ...options })
}

for (const width of [390, 1440]) test(`calendar reference menu works with button, right click and keyboard at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 950 })
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  await calendar(page)
  await start(page)
  if (width < 1024) await page.getByRole('button', { name: 'Show calendars', exact: true }).click()
  const row = page.locator('.calendar-choice').filter({ hasText: feed.label })
  await row.hover()
  await row.getByRole('button', { name: `Calendar settings · ${feed.label}`, exact: true }).click()
  await expect(page.getByRole('menuitem', { name: 'Hide calendar', exact: true })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'Request synchronization', exact: true })).toHaveCount(0)
  await page.getByRole('menuitem', { name: 'Copy reference', exact: true }).click()
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('galaris://calendar/9')
  await row.getByText(feed.label, { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Hide calendar', exact: true }).click()
  await expect(row.getByRole('checkbox')).not.toBeChecked()
  await expect(page.getByRole('button', { name: /Prepare synthetic review/ })).toHaveCount(0)
  await row.press('Shift+F10')
  await page.getByRole('menuitem', { name: 'Show calendar', exact: true }).click()
  await expect(row.getByRole('checkbox')).toBeChecked()
  await row.getByText(feed.label, { exact: true }).click({ button: 'right' })
  await page.screenshot({ path: testInfo.outputPath('calendar-context-menu.png'), fullPage: true })
  await page.getByRole('menuitem', { name: 'Calendar settings', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('textbox', { name: 'Label', exact: true })).toHaveValue(feed.label)
})

test('external calendar menu starts synchronization and respects edit permission', async ({ page }) => {
  const model = await calendar(page, { feeds: [{ ...feed, source_kind: 'caldav', is_default: false }] })
  let requests = 0, historyReads = 0, run = null
  await page.route('**/api/calendars/9/sync-runs?*', route => { historyReads++; return route.fulfill({ json: run ? [run] : [] }) })
  await page.route('**/api/calendars/9/test', route => {
    requests++
    run = { id: `00000000-0000-0000-0000-${String(requests).padStart(12, '0')}`, state: 'running', stage: 'read',
      started_at: new Date().toISOString(), finished_at: null, error_category: null, progress: null }
    return route.fulfill({ json: { calendar_id: 9, ok: true, sync_run_id: run.id, events_seen: 1, next_events: [] } })
  })
  await start(page)
  const row = page.locator('.calendar-choice').filter({ hasText: feed.label })
  await row.getByText(feed.label, { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Request synchronization', exact: true }).click()
  await expect.poll(() => requests).toBe(1)
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('status')).toContainText('In progress')
  const eventReads = model.queries.length
  Object.assign(run, { state: 'success', stage: 'complete', finished_at: new Date().toISOString(), progress: syncProgress({ calendar_changed: true, applied: 1 }) })
  await expect(dialog.getByRole('button', { name: /Completed/ })).toBeVisible()
  await expect.poll(() => model.queries.length).toBeGreaterThan(eventReads)
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'New synchronization', exact: true }).click()
  await expect.poll(() => requests).toBe(2)
  await expect(dialog.getByRole('status')).toContainText('In progress')
  const unchangedEventReads = model.queries.length
  Object.assign(run, { state: 'success', stage: 'complete', finished_at: new Date().toISOString(), progress: syncProgress({ applied: 2, downloaded: 2 }) })
  await expect(dialog.getByRole('button', { name: /Completed/ })).toBeVisible()
  const unchangedHistoryReads = historyReads
  await expect.poll(() => historyReads).toBeGreaterThan(unchangedHistoryReads)
  expect(model.queries.length).toBe(unchangedEventReads)
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'New synchronization', exact: true }).click()
  await expect.poll(() => requests).toBe(3)
  await expect(dialog.getByRole('status')).toContainText('In progress')
  Object.assign(run, { state: 'error', error_category: 'Synthetic sync failure', finished_at: new Date().toISOString(), progress: syncProgress({ calendar_changed: true, applied: 1 }) })
  await expect(dialog.getByRole('alert')).toContainText('Synthetic sync failure')
  await expect.poll(() => model.queries.length).toBeGreaterThan(unchangedEventReads)
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await setPrivileges(page, ['CALENDAR_ACCESS'])
  await row.getByText(feed.label, { exact: true }).click({ button: 'right' })
  await expect(page.getByRole('menuitem', { name: 'Request synchronization', exact: true })).toHaveCount(0)
})

test('calendar resource opens its real calendar through a deep link and supports retry', async ({ page }) => {
  await calendar(page, { feeds: [{ ...feed }, { ...feed, id: 10, label: 'Synthetic second calendar' }] })
  let unavailable = true
  await page.route('**/api/calendars/9', route => route.fulfill(unavailable ? { status: 404, json: { detail: 'Synthetic calendar unavailable' } } : { json: feed }))
  await mount(page, 'app/calendar/components/CalendarResourceDialog.vue', { props: { calendarId: 9 }, route: '/chat', privileges: ['CALENDAR_ACCESS'] })
  await expect(page.getByRole('alert')).toContainText('Synthetic calendar unavailable')
  unavailable = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Open calendar', exact: true })).toHaveAttribute('href', '/calendar?calendar_id=9&agent_id=7')
  await expect(page.getByRole('dialog').locator('img')).toHaveCount(0)
  await start(page, { route: '/calendar?calendar_id=9&date=2026-11-12&view=month&timezone=Europe%2FParis' })
  await expect(page.getByRole('checkbox', { name: feed.label, exact: true })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'Synthetic second calendar', exact: true })).not.toBeChecked()
  await expect(page.getByRole('button', { name: /Prepare synthetic review/ })).toBeVisible()
})

test('calendar color choices survive reopening and stay private to each user', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 950 })
  await calendar(page)
  await jsonRoute(page, '**/api/memory/agenda?*', { items: [], complete: true })
  await jsonRoute(page, '**/api/goals/agenda?*', { items: [], complete: true })
  const settingsOptions = { privileges: ['CALENDAR_EDIT', 'MEMORY_ACCESS', 'GOAL_ACCESS'] }
  const openPalette = async () => {
    await page.getByRole('button', { name: 'Show calendars', exact: true }).click()
    await page.getByText('Synthetic agenda', { exact: true }).click()
  }
  const choose = async color => {
    await page.getByRole('combobox', { name: 'Calendar color', exact: true }).click()
    await page.getByRole('option', { name: color, exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click()
  }
  await start(page, settingsOptions)
  await openPalette()
  await choose('Green')
  await expect(page.getByRole('combobox', { name: 'Calendar color', exact: true })).toHaveValue('Green')
  await page.screenshot({ path: testInfo.outputPath('calendar-colors-mobile.png'), fullPage: true })
  await start(page, settingsOptions)
  await openPalette()
  await expect(page.getByRole('combobox', { name: 'Calendar color', exact: true })).toHaveValue('Green')
  await start(page, { ...settingsOptions, user: { id: 2 } })
  await openPalette()
  await expect(page.getByRole('combobox', { name: 'Calendar color', exact: true })).not.toHaveValue('Green')
  await choose('Violet')
  await start(page, settingsOptions)
  await openPalette()
  await expect(page.getByRole('combobox', { name: 'Calendar color', exact: true })).toHaveValue('Green')
  for (const [layer, color] of [['Goals', 'Orange'], ['Memory', 'Red']]) {
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).last().click()
    await page.getByRole('button', { name: `Calendar settings: ${layer}`, exact: true }).click()
    await choose(color)
  }
  await start(page, settingsOptions)
  await page.getByRole('button', { name: 'Show calendars', exact: true }).click()
  for (const [layer, color] of [['Goals', 'Orange'], ['Memory', 'Red']]) {
    await page.getByRole('button', { name: `Calendar settings: ${layer}`, exact: true }).press('Enter')
    await expect(page.getByRole('combobox', { name: 'Calendar color', exact: true })).toHaveValue(color)
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).last().click()
  }
})

for (const width of [390, 1440]) test(`Memory agenda opens source content, retries and stays informational at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 950 })
  const model = await calendar(page)
  const memoryId = '00000000-0000-0000-0000-000000000101'
  const memory = { ...document, id: memoryId, title: 'Synthetic annual memory', node_kind: 'memory', media_type: 'text/html',
    payload: { text: '<p>Synthetic annual observation preserved in Memory.</p>' } }
  const occurrence = { id: '00000000-0000-0000-0000-000000000102', memory_id: memoryId, uri: `memory://${memoryId}`,
    title: memory.title, excerpt: 'Synthetic annual observation', revision: 3,
    start: '2026-11-12T00:00:00+01:00', end: '2026-11-13T00:00:00+01:00', all_day: true,
    timezone: 'Europe/Paris', temporal: { month: 11, day: 12 } }
  let failure = true, readCount = 0
  await page.route('**/api/memory/agenda?*', route => {
    readCount++
    if (failure) return route.fulfill({ status: 503, json: { detail: 'Synthetic memory read failure' } })
    const url = new URL(route.request().url())
    return route.fulfill({ json: { items: occurrence.start < url.searchParams.get('end') && occurrence.end > url.searchParams.get('start') ? [occurrence] : [], complete: true } })
  })
  await jsonRoute(page, `**/api/memory/items/${memoryId}?*`, memory)
  await start(page, { privileges: ['CALENDAR_EDIT', 'MEMORY_ACCESS'] })
  await expect(page.getByText('Unable to load the Memory agenda.', { exact: true })).toBeVisible()
  failure = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  const chip = page.getByRole('button', { name: /Synthetic annual memory/ })
  await expect(chip).toBeVisible()
  expect(model.stateReads.every(body => body.occurrences.every(row => row.event_id !== occurrence.id))).toBe(true)
  await chip.click()
  await expect(page.getByRole('dialog').getByText('Synthetic annual observation preserved in Memory.', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Add Task launch', exact: true })).toHaveCount(0)
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  if (width < 1024) await page.getByRole('button', { name: 'Show calendars', exact: true }).click()
  await page.getByRole('checkbox', { name: 'Memory', exact: true }).uncheck()
  await expect(chip).toHaveCount(0)
  await page.getByRole('checkbox', { name: 'Memory', exact: true }).check()
  await expect(chip).toBeVisible()
  expect(readCount).toBeGreaterThan(1)
  expect(model.writes).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('memory-agenda.png'), fullPage: true, animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('memory-agenda-dark.png'), fullPage: true, animations: 'disabled' })
})
async function taskDetails(page) {
  for (const [id, label] of [[taskId, 'Synthetic agenda Task'], [reviewTaskId, 'Synthetic review Task']]) {
    const task = { id, label, objective: '<p>Synthetic appointment work</p>', status: 'SUCCESS', paused: false, agent_id: null,
      tree_parent_id: null, parent_id: null, directly_linked: true, topic_id: null, data: {}, execution_result: result,
      revision: 1, created_at: event.start, updated_at: null, effort: 'standard', ai: true, cost: 0, messages: [] }
    await jsonRoute(page, `**/api/tasks/${id}/full`, task)
    await jsonRoute(page, `**/api/tasks/${id}`, task)
    await jsonRoute(page, `**/api/tasks/${id}/children`, [])
    await jsonRoute(page, `**/api/tasks/${id}/budget`, { enabled: false, scope: 'task_tree', provider_hard_cap: false,
      recorded_tokens: 0, recorded_cost: 0, active_phases: 0, reserved_tokens: 0, reserved_cost: 0,
      remaining_tokens: null, remaining_cost: null, remaining_seconds: null })
  }
  await jsonRoute(page, '**/api/tasks/activity', [])
  await jsonRoute(page, '**/api/topics?*', [])
}
async function openTaskInAgenda(page, buttonName, taskLabel) {
  const agendaUrl = page.url()
  await page.getByRole('dialog').getByRole('button', { name: buttonName, exact: true }).click()
  const taskDialog = page.getByRole('dialog').last()
  await expect(taskDialog.getByText(taskLabel, { exact: true })).toBeVisible()
  await expect(page).toHaveURL(agendaUrl)
  await page.screenshot({ path: test.info().outputPath(`${taskLabel.replaceAll(' ', '-')}-modal.png`), fullPage: true, animations: 'disabled' })
  await taskDialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await expect(page).toHaveURL(agendaUrl)
}

for (const width of [390, 1440]) test(`Goal agenda passages open their exact Task and refresh without duplicate calendar launches at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 950 })
  const model = await calendar(page)
  await taskDetails(page)
  const goalId = '00000000-0000-0000-0000-000000000095'
  const currentGoal = { ...goal, id: goalId, title: 'Synthetic daily Goal passage' }
  await jsonRoute(page, `**/api/goals/${goalId}`, currentGoal)
  await jsonRoute(page, `**/api/goals/${goalId}/cycles?*`, { items: [], total: 0, page: 1, page_size: 50 })
  await jsonRoute(page, '**/api/goals/tree', { items: [currentGoal], total: 1 })
  await jsonRoute(page, '**/api/goals/runtime-status', { globally_paused: false, schedule_enabled: false, timezone: 'UTC', is_active: true, inactive_reason: null, next_active_at: null })
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/agents/titles?*', [])
  const passage = { id: '00000000-0000-0000-0000-000000000096', goal_id: goalId,
    title: 'Synthetic daily Goal passage', scheduled_at: '2026-11-12T08:00:00Z', timezone: 'Europe/Paris',
    projected: true, state: 'scheduled', cycle_id: null, sequence: null, task_uri: null,
    review_task_uri: null, started_at: null, finished_at: null, verdict: null, reason: null }
  await page.route('**/api/goals/agenda?*', route => {
    const url = new URL(route.request().url())
    return route.fulfill({ json: { items: passage.scheduled_at >= url.searchParams.get('start') && passage.scheduled_at < url.searchParams.get('end') ? [passage] : [], complete: true } })
  })
  await start(page, { privileges: ['CALENDAR_EDIT', 'GOAL_ACCESS', 'TASK_ACCESS'] })
  await page.getByRole('button', { name: /Synthetic daily Goal passage/ }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(/Projected passage/)).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Open Task', exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  Object.assign(passage, { projected: false, state: 'running', cycle_id: 'synthetic-cycle', sequence: 4,
    task_uri: `galaris://task/${taskId}`, review_task_uri: `galaris://task/${reviewTaskId}`, started_at: '2026-11-12T08:10:00Z' })
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await page.getByRole('button', { name: /Synthetic daily Goal passage/ }).click()
  await expect(dialog.getByText('Cycle 4', { exact: true })).toBeVisible()
  await openTaskInAgenda(page, 'Open Task', 'Synthetic agenda Task')
  await openTaskInAgenda(page, 'Open review', 'Synthetic review Task')
  const agendaUrl = page.url()
  await dialog.getByRole('button', { name: 'Open Goal', exact: true }).click()
  const goalDialog = page.getByRole('dialog').last()
  await expect(goalDialog.getByRole('tab', { name: 'Goal', exact: true })).toBeVisible()
  await expect(goalDialog.getByText(currentGoal.title, { exact: true })).toBeVisible()
  await expect(page).toHaveURL(agendaUrl)
  await page.screenshot({ path: testInfo.outputPath('goal-modal.png'), fullPage: true, animations: 'disabled' })
  await goalDialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toHaveCount(1)
  await expect(page).toHaveURL(agendaUrl)
  for (const dark of [false, true]) {
    await page.evaluate(dark => window.testApp.dark(dark), dark)
    await page.screenshot({ path: testInfo.outputPath(`goal-passage-${dark ? 'dark' : 'light'}.png`), fullPage: true, animations: 'disabled' })
  }
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  expect(model.stateReads.every(batch => batch.occurrences.every(row => row.event_id !== passage.id))).toBeTruthy()
  expect(model.writes).toEqual([])
})

for (const width of [390, 1440]) test(`calendar opens an event, shows its Task and preserves event actions at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const model = await calendar(page, { actions: [{ id: 'synthetic-action', event_id: id, revision: 1, instructions: 'Existing synthetic instructions', anchor: 'start', offset_minutes: -10, active: true, recurrence_key: null, max_lateness_minutes: 60 }] })
  await taskDetails(page)
  await start(page)
  await expect(page.getByRole('button', { name: /Prepare synthetic review/ })).toBeVisible()
  await expect.poll(() => model.stateReads.length).toBeGreaterThan(0)
  await page.getByRole('button', { name: /Prepare synthetic review/ }).click()
  const panel = page.getByRole('dialog')
  await expect(panel.getByText('Synthetic event content')).toBeVisible()
  const exported = page.waitForEvent('download')
  await panel.getByRole('button', { name: 'Download event (.ics)', exact: true }).click()
  const calendarFile = await exported, chunks = []
  for await (const chunk of await calendarFile.createReadStream()) chunks.push(chunk)
  expect(Buffer.concat(chunks).toString('utf8')).toBe(detail.ical)
  await expect(panel.getByText('Completed', { exact: true })).toBeVisible()
  await openTaskInAgenda(page, 'Open Task', 'Synthetic agenda Task')
  await panel.getByRole('button', { name: 'Edit launch', exact: true }).click()
  const action = page.getByRole('dialog').last()
  await action.getByLabel('Task instructions', { exact: true }).fill('Prepare the synthetic review with its agenda')
  await action.getByLabel('Minutes', { exact: true }).fill('20')
  await action.getByRole('button', { name: 'Save launch', exact: true }).click()
  await expect.poll(() => model.writes.find(row => row.method === 'action')?.body).toMatchObject({ anchor: 'start', offset_minutes: -20, instructions: 'Prepare the synthetic review with its agenda', recurrence_key: null })
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await panel.getByRole('button', { name: 'Launch again', exact: true }).click()
  await page.getByRole('dialog').last().getByRole('button', { name: 'Launch again', exact: true }).click()
  await expect.poll(() => model.writes.find(row => row.method === 'relaunch')?.body).toMatchObject({ expected_event_revision: 1 })
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  for (const dark of [false, true]) {
    await page.evaluate(dark => window.testApp.dark(dark), dark)
    await page.screenshot({ path: testInfo.outputPath(`calendar-month-${dark ? 'dark' : 'light'}.png`), fullPage: true, animations: 'disabled' })
  }
  expect(model.queries.every(url => Date.parse(url.searchParams.get('end')) - Date.parse(url.searchParams.get('start')) <= 32 * 86400000)).toBe(true)
})

test('creating an event preserves all-day inclusive dates, recurrence and a failed event draft on retry', async ({ page }) => {
  const model = await calendar(page, { events: [], createFailure: true })
  const contactId = '00000000-0000-0000-0000-000000000105'
  const linked = { memory_item_id: contactId, owner_agent_id: 7, display_name: 'Synthetic calendar contact', identities: [], coordinates: { phone_numbers: [], postal_addresses: [] } }
  await jsonRoute(page, '**/api/contacts?*', { items: [linked], total: 1, limit: 50, offset: 0, has_more: false })
  await jsonRoute(page, `**/api/contacts/${contactId}`, linked)
  await start(page, { privileges: ['CALENDAR_EDIT', 'TASK_ACCESS', 'CONTACT_ACCESS'] })
  await page.getByRole('group', { name: 'Create event · Thursday, November 12, 2026', exact: true }).press('Enter')
  const editor = page.getByRole('dialog')
  await editor.getByLabel('Title', { exact: true }).fill('Synthetic workshop')
  await editor.getByRole('combobox', { name: 'Linked contact (optional)' }).click()
  await page.getByRole('option', { name: 'Synthetic calendar contact', exact: true }).click()
  await editor.getByRole('checkbox', { name: 'All day', exact: true }).check()
  await editor.getByLabel('Start date', { exact: true }).fill('2026-11-12')
  await editor.getByLabel('End date (inclusive)', { exact: true }).fill('2026-11-14')
  await editor.getByLabel('Repeat', { exact: true }).click(); await page.getByRole('option', { name: 'Weekly', exact: true }).click()
  await editor.getByLabel('Description', { exact: true }).fill('Prepare synthetic workshop')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(editor.getByRole('alert')).toContainText('Synthetic event save failure')
  await expect(editor.getByLabel('Description', { exact: true })).toHaveValue('Prepare synthetic workshop')
  expect(model.writes.filter(row => row.method === 'create')).toHaveLength(1)
  expect(model.writes[0].body).toMatchObject({ start: '2026-11-12', end: '2026-11-15', rrule: 'FREQ=WEEKLY;INTERVAL=1', contact_id: contactId })
  model.createFailure = false
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(editor.getByText('Synthetic workshop', { exact: true })).toBeVisible()
  expect(model.writes.filter(row => row.method === 'create')).toHaveLength(2)
  expect(model.writes.filter(row => row.method === 'action')).toHaveLength(0)
  expect(model.detail.contact_id).toBe(contactId)
})

test('clicking a blank day creates an all-day appointment while existing events and day navigation remain usable', async ({ page }) => {
  const model = await calendar(page)
  await start(page)
  const day = page.locator('.month-cell').filter({ has: page.getByRole('button', { name: 'Thursday, November 12, 2026', exact: true }) })
  await day.click({ position: { x: 8, y: 115 } })
  const editor = page.getByRole('dialog')
  await expect(editor.getByRole('checkbox', { name: 'All day', exact: true })).toBeChecked()
  await expect(editor.getByLabel('Start date', { exact: true })).toHaveValue('2026-11-12')
  await editor.getByLabel('Title', { exact: true }).fill('Synthetic whole-day appointment')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => model.writes.find(row => row.method === 'create')?.body).toMatchObject({ start: '2026-11-12', end: '2026-11-13' })
  await expect(page.getByRole('dialog').getByText('Synthetic whole-day appointment', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Thursday, November 12, 2026', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Day', exact: true })).toBeVisible()
})

for (const view of ['week', 'day']) test(`selecting 9–11 in ${view} opens and saves a two-hour appointment`, async ({ page }, testInfo) => {
  const model = await calendar(page, { events: [] })
  await start(page, { route: `/calendar?agent_id=7&date=2026-11-12&view=${view}&timezone=Europe%2FParis` })
  const startSlot = page.getByRole('button', { name: 'Create event · 2026-11-12 09:00', exact: true })
  const endSlot = page.getByRole('button', { name: 'Create event · 2026-11-12 11:00', exact: true })
  const startBox = await startSlot.boundingBox(), endBox = await endSlot.boundingBox()
  expect(startBox).not.toBeNull(); expect(endBox).not.toBeNull()
  await page.mouse.move(startBox.x + startBox.width / 2, startBox.y + startBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(endBox.x + endBox.width / 2, endBox.y + endBox.height / 2, { steps: 8 })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: '09:00 – 11:00' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath(`calendar-${view}-selection.png`), animations: 'disabled' })
  await page.mouse.up()
  const editor = page.getByRole('dialog')
  await expect(editor.getByLabel('Start time', { exact: true })).toHaveValue('09:00')
  await expect(editor.getByLabel('End time', { exact: true })).toHaveValue('11:00')
  await expect(editor.getByRole('checkbox', { name: 'All day', exact: true })).not.toBeChecked()
  await editor.getByLabel('Title', { exact: true }).fill('Synthetic selected appointment')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => model.writes.find(row => row.method === 'create')?.body).toMatchObject({ start: '2026-11-12T08:00:00.000Z', end: '2026-11-12T10:00:00.000Z' })
})

test.describe('event editing in another browser timezone', () => {
  test.use({ timezoneId: 'America/New_York' })
  test('a concurrent revision preserves the typed draft and reload restores the latest event', async ({ page }) => {
    const model = await calendar(page, { writeFailure: 409 })
    await start(page)
    await page.getByRole('button', { name: /Prepare synthetic review/ }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Edit', exact: true }).click()
    const editor = page.getByRole('dialog')
    await expect(editor.getByLabel('Start time', { exact: true })).toHaveValue('10:00')
    await editor.getByLabel('Title', { exact: true }).fill('Synthetic local draft')
    await editor.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(editor.getByText(/This event changed/)).toBeVisible()
    await expect(editor.getByLabel('Title', { exact: true })).toHaveValue('Synthetic local draft')
    expect(model.writes[0].body).toMatchObject({ expected_revision: 1, start: event.start, end: event.end })
    model.detail = { ...model.detail, revision: 2, summary: 'Synthetic remote update' }
    await editor.getByRole('button', { name: 'Reload current version', exact: true }).click()
    await expect(page.getByRole('dialog').getByLabel('Title', { exact: true })).toHaveValue('Synthetic remote update')
  })
})

test('read-only subscriptions still permit local Task instructions; read-only privileges hide mutations', async ({ page }) => {
  const model = await calendar(page, { feeds: [{ ...feed, writable: false, source_kind: 'ical' }], actions: [{ id: 'synthetic-action', event_id: id, revision: 1, instructions: 'Existing synthetic instructions', anchor: 'start', offset_minutes: -10, active: true, recurrence_key: null, max_lateness_minutes: 60 }] })
  await start(page, { privileges: ['CALENDAR_ACCESS'] })
  await expect(page.getByRole('button', { name: 'Create event', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: /Prepare synthetic review/ }).click()
  await expect(page.getByRole('dialog').getByText('Read-only calendar')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Edit launch', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Open Task' })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await setPrivileges(page, ['CALENDAR_EDIT'])
  await page.getByRole('button', { name: /Prepare synthetic review/ }).click()
  await expect(page.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Edit launch', exact: true })).toBeVisible()
  expect(model.writes).toEqual([])
})

test('calendar timezone selection, date navigation, all views and event deletion retain their event identities', async ({ page }, testInfo) => {
  const model = await calendar(page, { events: [event, { ...event, event_id: taskId, summary: 'Synthetic overlapping appointment', start: '2026-11-12T09:30:00Z' }] })
  await start(page)
  const timezone = page.getByRole('combobox', { name: 'Display timezone', exact: true })
  await timezone.click()
  const zoneSearch = page.getByRole('textbox', { name: 'Search', exact: true })
  await expect(zoneSearch).toBeFocused()
  await zoneSearch.fill('synthetic-zone-that-does-not-exist')
  await expect(page.getByText('No data', { exact: true })).toBeVisible()
  await expect(timezone).toHaveValue('Europe/Paris')
  await zoneSearch.fill('addis')
  await zoneSearch.press('ArrowDown')
  await zoneSearch.press('Enter')
  await expect(timezone).toHaveValue('Africa/Addis_Ababa')
  await expect(zoneSearch).toHaveCount(0)
  await timezone.click()
  await expect(zoneSearch).toHaveValue('')
  await zoneSearch.fill('Europe/Paris')
  await page.getByRole('option', { name: 'Europe/Paris', exact: true }).click()
  for (const view of ['Week', 'Day', 'Schedule', 'Month']) {
    await page.getByRole('group', { name: 'Calendar view', exact: true }).getByRole('button', { name: view, exact: true }).click()
    await expect(page.getByRole('button', { name: /Synthetic overlapping appointment/ })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`calendar-${view.toLowerCase()}.png`), fullPage: true })
  }
  await page.getByRole('button', { name: /Prepare synthetic review/ }).click()
  await page.getByRole('button', { name: 'Delete event', exact: true }).click()
  await page.getByRole('dialog').last().getByRole('button', { name: 'Delete event', exact: true }).click()
  await expect.poll(() => model.writes.find(row => row.method === 'DELETE')?.body).toEqual({ expected_revision: 1, scope: 'series' })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

for (const [width, view] of [[390, 'day'], [1440, 'week']]) test(`overlapping appointments remain individually reachable by pointer and keyboard in ${view}`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const events = [
    { ...event, event_id: 'long', summary: 'Synthetic long appointment', start: '2026-11-12T09:00:00Z', end: '2026-11-12T12:00:00Z' },
    { ...event, event_id: 'short', summary: 'Synthetic short appointment', start: '2026-11-12T09:00:00Z', end: '2026-11-12T09:05:00Z' },
    { ...event, event_id: 'next', summary: 'Synthetic next appointment', start: '2026-11-12T09:10:00Z', end: '2026-11-12T10:00:00Z' },
  ]
  await mount(page, 'app/calendar/components/CalendarBoard.vue', { props: {
    view, days: view === 'day' ? ['2026-11-12'] : ['2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13', '2026-11-14', '2026-11-15'],
    date: '2026-11-12', timezone: 'UTC', events, feeds: [feed], executions: {}, canCreate: true, canEdit: true,
  } })
  for (const row of events) {
    const button = page.getByRole('button', { name: new RegExp(row.summary) })
    await button.scrollIntoViewIfNeeded()
    await page.mouse.move(0, 0)
    const point = await button.evaluate(element => {
      const box = element.getBoundingClientRect()
      return { x: box.x + box.width / 2, y: box.top + Math.min(12, box.height / 2) }
    })
    await expect.poll(() => page.evaluate(point => document.elementFromPoint(point.x, point.y)?.closest('button')?.getAttribute('aria-label'), point)).toContain(row.summary)
    await page.mouse.click(point.x, point.y)
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'open').at(-1)?.value.event_id)).toBe(row.event_id)
    await button.focus()
    await button.press('Enter')
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'open').at(-1)?.value.event_id)).toBe(row.event_id)
    await button.evaluate(element => element.blur())
  }
  await page.mouse.move(0, 0)
  for (const dark of [false, true]) {
    await page.evaluate(dark => window.testApp.dark(dark), dark)
    await page.screenshot({ path: testInfo.outputPath(`overlaps-${dark ? 'dark' : 'light'}.png`), animations: 'disabled' })
    await page.getByRole('button', { name: /Synthetic short appointment/ }).focus()
    await page.screenshot({ path: testInfo.outputPath(`overlaps-focus-${dark ? 'dark' : 'light'}.png`), animations: 'disabled' })
    await page.getByRole('button', { name: /Synthetic short appointment/ }).evaluate(element => element.blur())
  }
})

test('mini calendar reaches both ends of its four-century year range and preserves the date until a day is chosen', async ({ page }, testInfo) => {
  const currentYear = new Date().getFullYear()
  await calendar(page)
  await start(page)
  const mini = page.locator('.calendar-mini-date')
  const selectedDate = page.getByLabel('Go to date', { exact: true })
  await mini.getByRole('button', { name: 'November', exact: true }).click()
  await mini.locator('.q-date__calendar').waitFor({ state: 'hidden' })
  await expect(mini.getByRole('button', { name: 'January', exact: true })).toBeVisible()
  await mini.screenshot({ path: testInfo.outputPath('mini-months.png'), animations: 'disabled' })
  await mini.getByRole('button', { name: 'Back', exact: true }).click()
  await mini.locator('.q-date__months').waitFor({ state: 'hidden' })
  await expect(mini.getByRole('button', { name: 'November', exact: true })).toBeFocused()
  await expect(selectedDate).toHaveValue('2026-11-12')
  await mini.getByRole('button', { name: 'November', exact: true }).click()
  await mini.locator('.q-date__calendar').waitFor({ state: 'hidden' })
  await mini.getByRole('button', { name: 'November', exact: true }).click()
  await mini.getByRole('button', { name: '2026', exact: true }).click()
  const active = mini.getByRole('button', { name: '2026', exact: true })
  await expect(active).toBeFocused()
  await mini.screenshot({ path: testInfo.outputPath('mini-years.png'), animations: 'disabled' })
  await active.press('Home')
  const firstYear = mini.getByRole('button', { name: String(currentYear - 200), exact: true })
  await expect(firstYear).toBeFocused()
  await firstYear.press('Enter')
  await expect(selectedDate).toHaveValue('2026-11-12')
  await mini.getByRole('button', { name: String(currentYear - 200), exact: true }).click()
  await mini.getByRole('button', { name: String(currentYear - 200), exact: true }).press('End')
  const lastYear = mini.getByRole('button', { name: String(currentYear + 200), exact: true })
  await expect(lastYear).toBeFocused()
  await lastYear.press('Enter')
  await expect(selectedDate).toHaveValue('2026-11-12')
  await mini.getByRole('button', { name: `12 November ${currentYear + 200}`, exact: true }).click()
  await expect(selectedDate).toHaveValue(`${currentYear + 200}-11-12`)
  await expect(page.getByRole('heading', { name: `November ${currentYear + 200}`, exact: true })).toBeVisible()
})

test('series editing preserves text drafts and uses the original series date, while dragging moves only the selected occurrence', async ({ page }) => {
  const model = await calendar(page, { events: [{ ...event, recurring: true }], detail: { ...detail, recurring: true, rrule: 'FREQ=WEEKLY;BYDAY=TH' }, master: { ...detail, recurring: true, rrule: 'FREQ=WEEKLY;BYDAY=TH', start: '2026-10-29T09:00:00Z', end: '2026-10-29T10:00:00Z' } })
  await start(page)
  await page.getByRole('button', { name: /Prepare synthetic review/ }).click()
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  const editor = page.getByRole('dialog')
  await editor.getByLabel('Title', { exact: true }).fill('Synthetic series draft')
  await editor.getByLabel('Apply changes to', { exact: true }).click(); await page.getByRole('option', { name: 'All events in the series', exact: true }).click()
  await expect(editor.getByLabel('Start date', { exact: true })).toHaveValue('2026-10-29')
  await expect(editor.getByLabel('Title', { exact: true })).toHaveValue('Synthetic series draft')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => model.writes.find(row => row.method === 'PUT')?.body).toMatchObject({ scope: 'series', start: '2026-10-29T09:00:00Z', expected_revision: 1 })
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Edit', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  // Move the original occurrence in a fresh workspace so its revision is explicit.
  model.events = [{ ...event, recurring: true }]; model.detail = { ...detail, recurring: true, rrule: 'FREQ=WEEKLY;BYDAY=TH' }
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  const chip = page.getByRole('button', { name: /Prepare synthetic review/ })
  const target = page.locator('.month-cell').filter({ has: page.getByRole('button', { name: 'Monday, November 16, 2026', exact: true }) })
  await chip.dragTo(target)
  await page.getByRole('dialog').getByRole('button', { name: 'Move event', exact: true }).click()
  await expect.poll(() => model.writes.filter(row => row.method === 'PUT').at(-1)?.body).toMatchObject({ scope: 'occurrence', recurrence_key: event.recurrence_key, start: '2026-11-16T09:00:00.000Z', end: '2026-11-16T10:00:00.000Z', expected_revision: 1 })
})

test('time selection supports reverse ranges, cancellation, keyboard and midnight without duplicate drafts', async ({ page }) => {
  const model = await calendar(page, { events: [] })
  await start(page, { route: '/calendar?agent_id=7&date=2026-11-12&view=day&timezone=Europe%2FParis' })
  async function drag(from, to, cancel = false) {
    const first = page.getByRole('button', { name: `Create event · 2026-11-12 ${from}`, exact: true })
    const last = page.getByRole('button', { name: `Create event · 2026-11-12 ${to}`, exact: true })
    await first.scrollIntoViewIfNeeded()
    const a = await first.boundingBox(), b = await last.boundingBox()
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
    await page.mouse.down(); await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 6 })
    if (cancel) await page.keyboard.press('Escape')
    await page.mouse.up()
  }
  await drag('09:00', '11:00', true)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: '09:00 – 11:00' })).toHaveCount(0)
  await drag('11:00', '09:00')
  let editor = page.getByRole('dialog')
  await expect(editor.getByLabel('Start time', { exact: true })).toHaveValue('09:00')
  await expect(editor.getByLabel('End time', { exact: true })).toHaveValue('11:00')
  await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const late = page.getByRole('button', { name: 'Create event · 2026-11-12 23:00', exact: true })
  await late.scrollIntoViewIfNeeded(); await late.focus(); await page.keyboard.press('Enter')
  editor = page.getByRole('dialog')
  await expect(editor.getByLabel('Start time', { exact: true })).toHaveValue('23:00')
  await expect(editor.getByLabel('End time', { exact: true })).toHaveValue('00:00')
  await expect(editor.getByLabel('End date (inclusive)', { exact: true })).toHaveValue('2026-11-13')
  await editor.getByLabel('Title', { exact: true }).fill('Synthetic midnight appointment')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => model.writes.filter(row => row.method === 'create')).toHaveLength(1)
  expect(model.writes.find(row => row.method === 'create').body).toMatchObject({ start: '2026-11-12T22:00:00.000Z', end: '2026-11-12T23:00:00.000Z' })
})

test('calendar settings save action activation and resolve conflicts using an explicit revision', async ({ page }) => {
  const model = await calendar(page, { feeds: [{ ...feed, source_kind: 'caldav', actions_enabled: false }] })
  const resolutions = []
  await jsonRoute(page, '**/api/calendars/9/sync-runs?*', [{ id: 'synthetic-conflict-run', started_at: event.start, finished_at: event.end, state: 'conflict', stage: 'push', error_category: 'Synthetic conflict', progress: null }])
  await jsonRoute(page, '**/api/calendars/9/conflicts?*', [{ event_id: id, revision: 3, local_ical: 'Synthetic local revision', remote_ical: 'Synthetic remote revision', local_deleted: false, remote_deleted: false }])
  await page.route(`**/api/calendars/9/events/${id}/resolve`, route => { resolutions.push(route.request().postDataJSON()); return route.fulfill({ json: { event_id: id, revision: 4 } }) })
  await start(page)
  await page.getByRole('checkbox', { name: feed.label, exact: true }).hover()
  await page.getByRole('button', { name: `Calendar settings · ${feed.label}`, exact: true }).click()
  await page.getByRole('menuitem', { name: 'Calendar settings', exact: true }).click()
  const settings = page.getByRole('dialog')
  await settings.getByRole('switch', { name: 'Enable Task launches for this calendar', exact: true }).check()
  await settings.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => model.writes.find(row => row.method === 'settings')?.body).toMatchObject({ actions_enabled: true })
  await settings.getByRole('textbox', { name: 'Label', exact: true }).fill('Unsaved synthetic calendar label')
  await settings.getByRole('tab', { name: 'Synchronization', exact: true }).click()
  await expect(settings.getByRole('spinbutton', { name: 'Automatic synchronization interval (hours)', exact: true })).toHaveCount(0)
  await expect(settings.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await settings.getByRole('tab', { name: 'Settings', exact: true }).click()
  await expect(settings.getByRole('textbox', { name: 'Label', exact: true })).toHaveValue('Unsaved synthetic calendar label')
  await settings.getByRole('tab', { name: 'Synchronization', exact: true }).click()
  for (const dark of [false, true]) {
    await page.evaluate(dark => window.testApp.dark(dark), dark)
    await page.screenshot({ path: test.info().outputPath(`calendar-sync-tab-${dark ? 'dark' : 'light'}.png`), fullPage: true, animations: 'disabled' })
  }
  await settings.getByRole('button', { name: 'Use remote version', exact: true }).click()
  await page.getByRole('dialog').last().getByRole('button', { name: 'Use remote version', exact: true }).click()
  await expect.poll(() => resolutions).toEqual([{ expected_revision: 3, choice: 'remote' }])
})

for (const width of [390, 1440]) test(`synchronized agenda opens its exact connection dialog with retry and saving at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  await calendar(page, { feeds: [{ ...feed, source_kind: 'caldav' }] })
  await jsonRoute(page, '**/api/calendars/9/conflicts?*', [])
  const connection = { id: 42, agent_id: 7, tool_id: 8, active: true }
  const params = { url: 'https://selected.example.test/calendar' }
  const tool = { id: 8, code: 'synthetic_calendar', label: 'Synthetic Calendar', can_edit: true, can_disable: true, has_calendar: true,
    global_params: {}, connection_schema: { params: { url: { type: 'string', label: 'Calendar URL', required: false } } } }
  await jsonRoute(page, '**/api/connections/tool-options', [tool])
  await jsonRoute(page, '**/api/mail/approvers', [])
  await page.route('**/api/connections/overview?*', route => route.fulfill({ json: [
    { ...connection, id: 99, agent_id: 8, params: { url: 'https://other.example.test/calendar' }, configured_params: [] },
    { ...connection, params, configured_params: [] },
  ] }))
  let fail = true
  await page.route('**/api/connections/42/params?*', route => {
    if (fail) { fail = false; return route.fulfill({ status: 503, json: { detail: 'Synthetic connection read failure' } }) }
    return route.fulfill({ json: { connection_id: 42, agent_id: 7, tool_id: 8, params, configured_params: [] } })
  })
  const writes = []
  await page.route('**/api/connections/42', route => { writes.push(route.request().postDataJSON()); return route.fulfill({ json: connection }) })
  await page.route('**/api/connections/42/params/bulk', route => {
    Object.assign(params, route.request().postDataJSON().params)
    return route.fulfill({ json: [] })
  })
  await start(page, { privileges: ['CALENDAR_EDIT', 'CONNECTION_ACCESS', 'CONNECTION_EDIT'] })
  const agendaRoute = await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)
  if (width < 1024) await page.getByRole('button', { name: 'Show calendars', exact: true }).click()
  await page.getByRole('checkbox', { name: feed.label, exact: true }).hover()
  await page.getByRole('button', { name: `Calendar settings · ${feed.label}`, exact: true }).click()
  await page.getByRole('menuitem', { name: 'Calendar settings', exact: true }).click()
  const settings = page.getByRole('dialog').first()
  await settings.getByRole('tab', { name: 'Synchronization', exact: true }).click()
  await page.screenshot({ path: testInfo.outputPath('calendar-sync-tab.png'), fullPage: true, animations: 'disabled' })
  await settings.getByRole('button', { name: 'Connection parameters', exact: true }).click()
  let dialog = page.getByRole('dialog').last()
  await expect(dialog.getByRole('alert')).toBeVisible()
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByLabel('Calendar URL', { exact: true })).toHaveValue(params.url)
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(agendaRoute)
  await page.screenshot({ path: testInfo.outputPath('connection-over-agenda.png'), fullPage: true, animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  expect(writes).toHaveLength(0)
  await settings.getByRole('button', { name: 'Connection parameters', exact: true }).click()
  dialog = page.getByRole('dialog').last()
  await dialog.getByLabel('Calendar URL', { exact: true }).fill('https://updated.example.test/calendar')
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await expect.poll(() => params.url).toBe('https://updated.example.test/calendar')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(agendaRoute)
  expect(writes).toHaveLength(1)
})

test('a new synchronization cannot be replaced by an older history response', async ({ page }) => {
  let held, reads = 0
  const current = { id: 'synthetic-current-run', state: 'running', stage: 'read', started_at: event.start, finished_at: null, progress: null }
  await page.route('**/api/calendars/9/sync-runs?*', route => {
    if (++reads === 1) { held = route; return }
    return route.fulfill({ json: [current] })
  })
  await jsonRoute(page, '**/api/calendars/9/test', { calendar_id: 9, ok: true, sync_run_id: current.id, events_seen: 0, next_events: [] })
  await mount(page, 'app/calendar/components/CalendarSyncMonitor.vue', { props: { calendarId: 9 } })
  await expect.poll(() => Boolean(held)).toBe(true)
  await page.getByRole('button', { name: 'New synchronization', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('In progress')
  await held.fulfill({ json: [{ ...current, id: 'synthetic-old-run', state: 'success' }] }).catch(() => {})
  await expect(page.getByRole('status')).toContainText('In progress')
  await expect(page.getByRole('button', { name: 'New synchronization', exact: true })).toBeDisabled()
})

for (const width of [390, 1440]) test(`synchronization monitoring follows the requested run, live counters and retained failures at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const stamp = new Date().toISOString()
  const progress = { steps: [], server_reached: false, network_phase: null, http_requests: 0, last_http_status: null, calendars: 0,
    downloaded: 0, download_total: null, applied: 0, apply_total: null, uploaded: 0, upload_total: null, upload_succeeded: 0,
    conflicts: 0, deleted: 0, bytes_received: 0, bytes_sent: 0, transfer_completed: 0, transfer_total: null }
  let run = null, reads = 0, starts = 0
  const history = []
  await page.route('**/api/calendars/9/sync-runs?*', route => {
    reads++
    const query = new URL(route.request().url()).searchParams
    expect(['1', '50']).toContain(query.get('limit'))
    if (query.has('run_id')) expect(query.get('run_id')).toBe(run.id)
    return route.fulfill({ json: query.has('run_id') ? history.filter(row => row.id === query.get('run_id')) : [...history].reverse() })
  })
  await page.route('**/api/calendars/9/test', route => {
    starts++
    run = { id: `00000000-0000-0000-0000-${String(starts).padStart(12, '0')}`, stage: 'queued', state: 'queued', error_category: null, http_status: null, started_at: stamp, finished_at: null, progress: structuredClone(progress) }
    history.push(run)
    return route.fulfill({ json: { calendar_id: 9, ok: true, events_seen: 0, next_events: [], sync_run_id: run.id } })
  })
  await mount(page, 'app/calendar/components/CalendarSyncMonitor.vue', { props: { calendarId: 9 } })
  await expect.poll(() => reads).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'New synchronization', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Queued' })).toBeVisible()
  Object.assign(run, { state: 'running', stage: 'read' })
  Object.assign(run.progress, { server_reached: true, network_phase: 'download', http_requests: 3, last_http_status: 207,
    calendars: 1, downloaded: 2, download_total: 5, bytes_received: 4096,
    steps: [{ stage: 'connecting', started_at: stamp, finished_at: stamp }, { stage: 'read', started_at: stamp, finished_at: null }] })
  const downloaded = page.locator('.sync-history > .q-list > .q-expansion-item').first().getByRole('row', { name: /Resources downloaded/ })
  await expect(downloaded).toContainText('2/5')
  await expect(page.getByText('Preparing connection', { exact: true })).toBeVisible()
  await expect(page.getByText(/Server reached/)).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('sync-download.png'), fullPage: true })
  run.stage = 'push'
  Object.assign(run.progress, { downloaded: 5, applied: 5, apply_total: 5, uploaded: 1, upload_total: 3, upload_succeeded: 1 })
  await expect(page.getByRole('row', { name: /Upload operations processed/ })).toContainText('1/3')
  run.state = 'success'; run.stage = 'complete'; run.finished_at = stamp
  Object.assign(run.progress, { uploaded: 3, upload_succeeded: 3 })
  await expect(page.getByRole('button', { name: /Completed/ })).toBeVisible()
  expect(starts).toBe(1)
  await page.getByRole('button', { name: 'New synchronization', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Queued' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Completed/ })).toBeVisible()
  Object.assign(run, { state: 'error', stage: 'read', error_category: 'ReadTimeout', http_status: 504, finished_at: stamp })
  Object.assign(run.progress, { server_reached: true, downloaded: 2, download_total: 5 })
  await expect(page.getByRole('alert')).toContainText('ReadTimeout')
  await expect(page.getByText('Preparing connection', { exact: true })).toHaveCount(0)
  await expect(downloaded).toContainText('2/5')
  await mount(page, 'app/calendar/components/CalendarSyncMonitor.vue', { props: { calendarId: 9 } })
  await expect(page.getByRole('alert')).toContainText('ReadTimeout')
  await page.locator('.sync-history > .q-list > .q-expansion-item').first().getByRole('button', { name: 'Technical details' }).click()
  await expect(page.getByRole('row', { name: /Data received/ })).toBeVisible()
  for (const dark of [false, true]) {
    await page.evaluate(dark => window.testApp.dark(dark), dark)
    await page.screenshot({ path: testInfo.outputPath(`sync-failure-${dark ? 'dark' : 'light'}.png`), fullPage: true })
  }
})

test('a late response for a previous period cannot replace the current calendar; errors remain retryable', async ({ page }) => {
  await calendar(page)
  let held, fail = false
  await page.route('**/api/calendars/events?*', async route => {
    const url = new URL(route.request().url())
    if (url.searchParams.get('start').startsWith('2026-10-')) { held = route; return }
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Synthetic period failure' } })
    return route.fulfill({ json: { items: [], complete: true, stale_calendar_ids: [], total: 0 } })
  })
  await start(page)
  await expect.poll(() => Boolean(held)).toBe(true)
  await page.getByRole('button', { name: 'Next period', exact: true }).click()
  await held.fulfill({ json: { items: [event], complete: true, stale_calendar_ids: [], total: 1 } }).catch(() => {})
  await expect(page.getByRole('heading', { name: 'December 2026', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Prepare synthetic review/ })).toHaveCount(0)
  fail = true
  await page.getByRole('button', { name: 'Next period', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Synthetic period failure')
  fail = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('the personal default remains protected alongside calendars identified by their external Tool', async ({ page }) => {
  await calendar(page, { feeds: [{ ...feed, id: 10, label: 'Synthetic external calendar', source_kind: 'caldav',
    is_default: false, tool_label: 'Synthetic calendar provider' }, { ...feed }] })
  await start(page)
  await expect(page.getByText('Synthetic calendar provider', { exact: true })).toBeVisible()
  const personalCheckbox = page.getByRole('checkbox', { name: feed.label, exact: true })
  await page.getByText(feed.label, { exact: true }).click()
  await expect(personalCheckbox).toBeChecked()
  await expect(page.getByRole('dialog').getByRole('textbox', { name: 'Label', exact: true })).toHaveValue(feed.label)
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).last().click()
  await personalCheckbox.uncheck()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Prepare synthetic review/ })).toHaveCount(0)
  await personalCheckbox.focus()
  await page.keyboard.press('Space')
  await expect(personalCheckbox).toBeChecked()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Prepare synthetic review/ })).toBeVisible()
  await page.getByRole('group', { name: 'Create event · Thursday, November 12, 2026', exact: true }).press('Enter')
  await expect(page.getByRole('dialog').getByRole('combobox', { name: 'Calendar', exact: true })).toHaveValue(feed.label)
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.getByRole('button', { name: `Calendar settings: ${feed.label}`, exact: true }).press('Enter')
  await expect(page.getByRole('dialog').getByRole('textbox', { name: 'Label', exact: true })).toHaveValue(feed.label)
  await expect(page.getByRole('button', { name: 'Delete calendar', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Create calendar', exact: true })).toHaveCount(0)
  await expect(page.getByRole('switch', { name: 'Enabled', exact: true })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Synchronization', exact: true })).toHaveCount(0)
  await expect(page.getByText('Last synchronized', { exact: false })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Request synchronization', exact: true })).toHaveCount(0)
})
