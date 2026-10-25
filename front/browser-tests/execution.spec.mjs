import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'
import { agent, call, document, result } from './data.mjs'

for (const width of [390, 1280]) {
  test(`tool details survive live updates and reopening (${width})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const message = { type: 'tool', tool_name: 'file_read', tool_call_external_id: 'synthetic-call',
      content: 'Synthetic result', tool_arguments: { uri: 'synthetic://report', query: 'Synthetic query' },
      tool_result: { count: 3, uri: 'synthetic://result' }, success: true }
    await mount(page, 'app/task/components/ExecutionResult.vue', { props: {
      executionResult: { ...result, messages: [message] }, running: true, embedded: true,
    } })
    const header = page.getByRole('button', { name: /file_read/ })
    const output = page.getByRole('region', { name: 'Returned content', exact: true })
    await expect(page.getByRole('cell', { name: 'synthetic://report', exact: true })).toBeVisible()
    await expect(output).toContainText('"count": 3')
    await page.evaluate(({ message, result }) => window.testApp.setProps({ running: false,
      executionResult: { ...result, messages: [{ ...message,
        success: false, content: 'Synthetic denial', tool_result: { error: 'Synthetic denial' } }] },
    }), { message, result })
    await expect(header).toContainText('Failure')
    await expect(output).toContainText('Synthetic denial')
    await header.press('Enter')
    await expect(output).not.toBeVisible()
    await header.press('Space')
    await expect(output).toBeInViewport({ ratio: 1 })
    await page.screenshot({ path: `/artifacts/tool-details-${width}.png` })
  })
}

test('task activity warns only during silence and clears as soon as motion resumes', async ({ page }) => {
  const at = new Date()
  await page.clock.install({ time: at })
  const activity = { task_id: 'synthetic-silence', phase: 'EXEC', revision: 1,
    operational: { operational_state: 'RUNNING', waits: [] }, pause_pending: false,
    attempt_number: 1, last_activity_at: at.toISOString(), streams_ai_messages: true }
  await mount(page, 'app/task/components/TaskActivitySummary.vue', { props: { activity } })
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.clock.fastForward(121_000)
  await expect(page.getByRole('alert')).toContainText('No activity received')
  await expect(page.getByRole('alert')).toContainText('Execution continues')
  await page.screenshot({ path: '/artifacts/task-silence-warning.png' })
  for (const motion of ['reasoning', 'text', 'tool arguments', 'tool result']) {
    await page.evaluate(activity => window.testApp.setProps({ activity: {
      ...activity, last_activity_at: new Date().toISOString(),
    } }), activity)
    await expect(page.getByRole('alert'), motion).toHaveCount(0)
    await page.clock.fastForward(121_000)
    await expect(page.getByRole('alert')).toContainText('No activity received')
  }
  await page.evaluate(activity => window.testApp.setProps({ activity: {
    ...activity, operational: { operational_state: 'WAITING', waits: [] },
  } }), activity)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.evaluate(activity => window.testApp.setProps({ activity, unavailable: true }), activity)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('Activity unavailable; refresh on reconnect.')).toBeVisible()
})

test('silence warning allows a scoped manual recovery and explains refusals without stopping the task', async ({ page }) => {
  const activity = { task_id: 'synthetic-recovery', run_id: 'synthetic-run', phase: 'EXEC', revision: 1,
    operational: { operational_state: 'RUNNING', waits: [] }, pause_pending: false,
    attempt_number: 1, latest_attempt: { id: 'synthetic-attempt' },
    last_activity_at: new Date(Date.now() - 130_000).toISOString(), streams_ai_messages: true,
    call_recovery_supported: true }
  const requests = []
  await page.route('**/api/tasks/synthetic-recovery/recover-call', async route => {
    const command = route.request().postDataJSON()
    requests.push(command)
    await route.fulfill({ json: { run_id: command.run_id, request_id: command.request_id,
      version: command.expected_control_version + 1, state: 'requested' } })
  })
  await mount(page, 'app/task/components/TaskActivitySummary.vue', { props: { activity }, privileges: ['TASK_EDIT'] })
  const action = page.getByRole('button', { name: 'Interrupt call and resume' })
  await action.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('Recovery requested; the runtime is checking the current call.')).toBeVisible()
  await expect(action).toBeDisabled()
  expect(requests).toHaveLength(1)
  expect(requests[0].run_id).toBe(activity.run_id)
  expect(requests[0].expected_control_version).toBe(0)
  expect(requests[0].request_id).toMatch(/^[a-f0-9-]{36}$/)
  await page.evaluate(({ activity, request }) => window.testApp.setProps({ activity: { ...activity,
    call_recovery: { run_id: activity.run_id, request_id: request.request_id, version: 1, state: 'refused' },
  } }), { activity, request: requests[0] })
  await expect(page.getByText(/Call was not interrupted/)).toBeVisible()
  await expect(action).toBeEnabled()
  await action.click()
  await expect(action).toBeDisabled()
  expect(requests[1].expected_control_version).toBe(1)
  await page.evaluate(({ activity, request }) => window.testApp.setProps({ activity: { ...activity,
    last_activity_at: new Date().toISOString(),
    call_recovery: { run_id: activity.run_id, request_id: request.request_id, version: 2, state: 'accepted' },
  } }), { activity, request: requests[1] })
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('Call interruption accepted; resuming with guidance to change approach.')).toBeVisible()
  await expect(page.getByText('Running', { exact: true })).toBeVisible()
  await page.evaluate(activity => window.testApp.setProps({ activity }), activity)
  await setPrivileges(page, ['TASK_ACCESS'])
  await expect(action).toHaveCount(0)
})

for (const context of ['task', 'run', 'attempt', 'reopen']) {
test(`manual recovery errors and late responses never affect another execution (${context})`, async ({ page }) => {
  if (context === 'task') await page.setViewportSize({ width: 390, height: 844 })
  const activity = { task_id: 'synthetic-recovery', run_id: 'synthetic-run', phase: 'EXEC', revision: 1,
    operational: { operational_state: 'RUNNING', waits: [] }, pause_pending: false,
    attempt_number: 1, latest_attempt: { id: 'synthetic-attempt' },
    last_activity_at: new Date(Date.now() - 130_000).toISOString(),
    streams_ai_messages: true, call_recovery_supported: true }
  let releaseOld, releaseNew
  const pendingOld = new Promise(resolve => { releaseOld = resolve })
  const pendingNew = new Promise(resolve => { releaseNew = resolve })
  const requests = []
  let oldFinished = false
  await page.route('**/api/tasks/*/recover-call', async route => {
    const command = route.request().postDataJSON()
    requests.push(command)
    if (requests.length === 1) {
      await route.fulfill({ status: 409, json: { detail: 'Synthetic stale execution. Refresh activity.' } })
    } else {
      const old = requests.length === 2
      await (old ? pendingOld : pendingNew)
      if (old && context === 'task') {
        await route.fulfill({ status: 409, json: { detail: 'Synthetic old request refused.' } })
      } else {
        await route.fulfill({ json: { ...command, version: 1, state: 'requested' } })
      }
      if (old) oldFinished = true
    }
  })
  await mount(page, 'app/task/components/TaskActivitySummary.vue', { props: { activity }, privileges: ['TASK_EDIT'] })
  const action = page.getByRole('button', { name: 'Interrupt call and resume' })
  await action.click()
  await expect(page.getByText('Synthetic stale execution. Refresh activity.')).toBeVisible()
  await expect(action).toBeEnabled()
  await action.click()
  await expect(action).toBeDisabled()
  await expect.poll(() => requests.length).toBe(2)
  const changed = { ...activity,
    ...(context === 'task' ? { task_id: 'new-task' }
      : context === 'attempt' ? { latest_attempt: { id: 'new-attempt' } }
      : { run_id: 'new-run' }),
  }
  await page.evaluate(activity => window.testApp.setProps({ activity }), changed)
  await expect(action).toBeEnabled()
  if (context === 'reopen') {
    await page.evaluate(activity => window.testApp.setProps({ activity }), activity)
  }
  await action.click()
  await expect(action).toBeDisabled()
  await expect.poll(() => requests.length).toBe(3)
  releaseOld()
  await expect.poll(() => oldFinished).toBe(true)
  await expect(action).toBeDisabled()
  await expect(page.getByText('Recovery requested; the runtime is checking the current call.')).toHaveCount(0)
  await expect(page.getByText('Synthetic stale execution. Refresh activity.')).toHaveCount(0)
  await expect(page.getByText('Synthetic old request refused.')).toHaveCount(0)
  releaseNew()
  await expect(page.getByText('Recovery requested; the runtime is checking the current call.')).toBeVisible()
  await expect(action).toBeDisabled()
  expect(requests[2].run_id).toBe(context === 'run' ? changed.run_id : activity.run_id)
  expect(new Set(requests.map(request => request.request_id)).size).toBe(3)
})
}

test('initial task timing recovers historical processing and preserves timing across reopening', async ({ page }) => {
  const timing = {
    task_id: 'task-timing', label: 'Generated image',
    preparation_started_at: '2026-09-13T05:44:40Z', preparation_finished_at: '2026-09-13T05:44:55Z',
    enqueued_at: '2026-09-13T05:44:55.200Z', first_claimed_at: '2026-09-13T05:44:55.300Z',
    preparation_seconds: 15, admission_seconds: 0.2, queue_wait_upper_bound_seconds: 0.1,
    claimed_to_output_seconds: 5.7, enqueued_to_output_seconds: 5.8,
    execution_timing: { first_call_at: '2026-09-13T05:44:55.400Z', first_output_at: '2026-09-13T05:45:01Z',
      first_output_seconds: 5.6, call_seconds_before_output: 4.6, between_calls_seconds: 1 },
  }
  const props = { timing, showTask: true }
  await mount(page, 'app/task/components/TaskStartupTiming.vue', { props })
  const panel = page.getByRole('region', { name: 'Initial startup' })
  await expect(panel).toContainText('galaris://task/task-timing')
  await expect(panel.locator('dl').first()).toContainText('15 s')
  await expect(panel.locator('dl').first()).toContainText('0.1 s')
  await expect(panel.locator('dl').first()).toContainText('5.7 s')
  await expect(panel.getByRole('region', { name: 'Time to first useful output' })).toContainText('5.6 s')
  await expect(panel.getByRole('region', { name: 'Time to first useful output' })).toContainText('4.6 s')
  await panel.getByText('Observed timestamps', { exact: true }).click()
  await expect(panel).toContainText('2026')
  await page.evaluate(timing => window.testApp.setProps({ timing: {
    ...timing, task_id: 'historical', label: 'Historical task',
    preparation_seconds: 4, preparation_source: 'llm_calls', preparation_to_first_call_seconds: 1,
    admission_seconds: null, queue_wait_upper_bound_seconds: null,
    preparation_started_at: '2026-09-13T05:44:40Z', preparation_finished_at: '2026-09-13T05:44:44Z',
    enqueued_at: null, first_claimed_at: null,
    claimed_to_output_seconds: null, enqueued_to_output_seconds: null,
    execution_timing: { first_call_at: null, first_output_at: null,
      first_output_seconds: null, call_seconds_before_output: null, between_calls_seconds: null },
    processing_intervals: [{ call_id: 'historical-call', purpose: 'agent.dispatch',
      started_at: '2026-09-13T05:44:45Z', completed_at: '2026-09-13T05:44:53Z', seconds: 8 }],
  } }), timing)
  await panel.getByText('LLM processing: timestamps recovered from the call ledger').click()
  await expect(panel).toContainText('agent.dispatch')
  await expect(panel).toContainText('8 s')
  await expect(panel.locator('dl').first()).toContainText('Objective preparation (LLM calls)')
  await expect(panel.locator('dl').first()).toContainText('4 s')
  await expect(panel.getByRole('region', { name: 'Time to first useful output' }).getByText('Not measured', { exact: true })).toHaveCount(3)
  await expect(panel).not.toContainText('5.6 s')
  await expect(panel).not.toContainText('15 s')
  await expect(panel).not.toContainText('galaris://task/task-timing')
  await mount(page, 'app/task/components/TaskStartupTiming.vue', { props })
  await expect(page.getByRole('region', { name: 'Initial startup' }).locator('dl').first()).toContainText('0.1 s')
})

test('agent selector exposes an accessible label, placeholder, selection and clearing', async ({ page }) => {
  await jsonRoute(page, '**/api/agents?*', [agent])
  await mount(page, 'app/agent/components/AgentSelect.vue', { props: { label: 'Worker', modelValue: null, clearable: true, options: [{ label: 'Alice Example', value: 7 }, { label: 'Outside agent', value: 99 }] } })
  const select = page.getByRole('combobox', { name: 'Worker' })
  await expect(select).toBeVisible()
  await expect(page.locator('.q-field__native')).toContainText('Agent')
  await select.click()
  await expect(page.getByRole('option', { name: 'Outside agent' })).toHaveCount(0)
  await page.getByRole('option', { name: 'Alice Example' }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toBe(7)
  await expect(page.locator('.q-field__native')).toContainText('Alice Example')
  await page.locator('.q-field__focusable-action').click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toBe(null)
})

test('agent selection clears revoked choices and ignores a response from an obsolete scope', async ({ page }) => {
  let release
  let requested = false
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/agents/selection?scope=management', async route => {
    requested = true
    await pending
    await route.fulfill({ json: [{ id: 7, label: 'Managed agent', has_avatar: false }] })
  })
  await jsonRoute(page, '**/api/agents/selection?scope=dialogue', [{ id: 8, label: 'Team agent', has_avatar: false }])
  await mount(page, 'app/agent/components/AgentSelect.vue', { props: {
    modelValue: null, loadAgents: false, options: [{ value: 7, label: 'Managed agent' }, { value: 8, label: 'Team agent' }],
  } })
  await page.getByRole('combobox').click()
  await expect.poll(() => requested).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ scope: 'dialogue' }))
  release()
  await expect(page.getByRole('option', { name: 'Managed agent', exact: true })).toHaveCount(0)
  await page.getByRole('option', { name: 'Team agent', exact: true }).click()
  await expect(page.locator('.q-field__native')).toContainText('Team agent')
  await page.route('**/api/agents/selection?scope=dialogue', route => route.fulfill({ status: 403, json: { detail: 'Revoked' } }))
  await setPrivileges(page, ['CHAT_ACCESS'])
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toBe(null)
  await expect(page.locator('.q-field__native')).not.toContainText('Team agent')
})

test('live conversation progress survives delayed detail loading and stale snapshots', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  let releaseView, viewReads = 0
  const viewPending = new Promise(resolve => { releaseView = resolve })
  await page.route('**/app/task/components/ExecutionResult.vue', async route => {
    viewReads++
    await viewPending
    await route.continue()
  })
  const requested = []
  await page.route('**/api/conversations/rounds/round-a', async route => {
    requested.push('round')
    await pending
    await route.fulfill({ json: {
      id: 'round-a', status: 'RUNNING', attempt_count: 2,
      task_startup_timings: [{ task_id: 'task-a', label: 'Delegated task', preparation_seconds: 3 }],
      execution_result: { ...result, result: '', messages: [] },
    } })
  })
  await page.route('**/api/llm-calls?*', async route => {
    expect(new URL(route.request().url()).searchParams.get('conversation_round_id')).toBe('round-a')
    requested.push('calls')
    await pending
    await route.fulfill({ json: [{ ...call, conversation_round_id: 'round-a' }] })
  })
  const liveRound = { room_id: 'room-a', round_id: 'round-a', active: true, success: null, last_sequence: 1, topic_id: null,
    ai_result: { ...result, result: '', messages: [{ type: 'text', content: 'Current progress' }] } }
  await mount(page, 'app/chat/components/AgentExecutionTrace.vue', { props: { roomId: 'room-a', liveRound } })
  try {
    expect(viewReads).toBe(0)
    await page.locator('.trace-summary').click()
    await expect.poll(() => requested.length).toBe(2)
    await expect.poll(() => viewReads).toBe(1)
    await expect(page.locator('.trace-summary')).toHaveAttribute('aria-expanded', 'true')
    releaseView()
    await expect(page.locator('.trace-detail p').filter({ hasText: /^Current progress$/ })).toBeVisible()
    await expect(page.getByRole('tab', { name: /memory/i })).toBeVisible()
    await expect(page.locator('.summary-metrics')).not.toContainText('$')
    await page.getByRole('tab', { name: 'Details', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Detailed state', exact: true })).toContainText('Running')
  } finally { releaseView(); release() }
  await expect(page.getByRole('region', { name: 'Detailed state', exact: true })).toContainText('2 attempt(s)')
  await expect(page.getByRole('region', { name: 'Initial startup', exact: true })).toContainText('galaris://task/task-a')
  await expect(page.getByRole('region', { name: 'Recorded usage', exact: true })).toContainText('118 tokens · $0.0001')
  await page.evaluate(data => window.testApp.emitSocket('llm_call.update', { data }),
    { ...call, conversation_round_id: 'round-a', total_tokens: 200, cost: 0.25 })
  await expect(page.getByRole('region', { name: 'Recorded usage', exact: true })).toContainText('200 tokens · $0.2500')
  await page.locator('.trace-summary').click()
  await page.locator('.trace-summary').click()
  await expect(page.getByRole('region', { name: 'Initial startup', exact: true })).toContainText('3 s')
  await page.getByRole('tab', { name: 'Reasoning steps', exact: true }).click()
  await expect(page.locator('.trace-detail p').filter({ hasText: /^Current progress$/ })).toBeVisible()
  await page.evaluate(liveRound => window.testApp.setProps({ liveRound: { ...liveRound, last_sequence: 2,
    ai_result: { ...liveRound.ai_result, messages: [{ type: 'text', content: 'Current progress, continued' }] } } }), liveRound)
  await expect(page.locator('.trace-detail p').filter({ hasText: /^Current progress, continued$/ })).toBeVisible()
})

test('a context change rewrites the response without reporting an execution failure', async ({ page }) => {
  const liveRound = { room_id: 'room-a', round_id: 'round-a', active: true, success: true,
    last_sequence: 1, topic_id: null, ai_result: { ...result, metadata: {} } }
  const activity = { id: 'round-a', status: 'RUNNING', tools_used: [], cost: 0, execution_time: 1 }
  await mount(page, 'app/chat/components/AgentExecutionTrace.vue', { props: { roomId: 'room-a', liveRound, activity } })
  const summary = page.getByRole('button', { name: /Thinking/ })
  await expect(summary).toBeVisible()
  // The terminal runtime event can arrive before the durable activity projection.
  await page.evaluate(liveRound => window.testApp.setProps({ liveRound: { ...liveRound,
    active: false, success: false,
    ai_result: { ...liveRound.ai_result, metadata: { interrupted_by_new_input: true } },
  } }), liveRound)
  await expect(page.getByRole('button', { name: /Rewriting response/ })).toBeVisible()
  await expect(page.getByText('The execution encountered a problem')).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('rewriting-light.png') })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: test.info().outputPath('rewriting-dark.png') })
  // A superseded draft may also have been interrupted before the runtime prepared metadata.
  await page.evaluate(({ liveRound, activity }) => window.testApp.setProps({
    liveRound: { ...liveRound, active: false, success: false },
    activity: { ...activity, status: 'SUPERSEDED' },
  }), { liveRound, activity })
  await expect(page.getByRole('button', { name: /Rewriting response/ })).toBeVisible()
  await page.evaluate(liveRound => window.testApp.setProps({
    activity: undefined, liveRound: { ...liveRound, round_id: 'round-b' },
  }), liveRound)
  await expect(summary).toBeVisible()
  // A real failure in the new response must still be reported.
  await page.evaluate(liveRound => window.testApp.setProps({ liveRound: {
    ...liveRound, round_id: 'round-b', active: false, success: false,
  } }), liveRound)
  await expect(page.getByRole('button', { name: /The execution encountered a problem/ })).toBeVisible()
  await expect(page.getByText('Rewriting response…')).toHaveCount(0)
})

test('chat execution details ignore a late previous round and recover usage after a failed load', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  let requested = false
  let callsFail = true
  await page.route('**/api/conversations/rounds/*', async route => {
    const previous = route.request().url().endsWith('/round-a')
    if (previous) {
      requested = true
      await pending
    }
    await route.fulfill({ json: { id: previous ? 'round-a' : 'round-b', status: 'SUCCEEDED',
      attempt_count: previous ? 9 : 1, execution_result: result,
      task_startup_timings: [{ task_id: previous ? 'old-task' : 'current-task', label: previous ? 'Old work' : 'Current work', preparation_seconds: 2 }],
    } })
  })
  await page.route('**/api/llm-calls?*', async route => {
    const previous = new URL(route.request().url()).searchParams.get('conversation_round_id') === 'round-a'
    if (previous) await pending
    if (!previous && callsFail) return route.fulfill({ status: 503, json: { detail: 'Usage unavailable' } })
    await route.fulfill({ json: [{ ...call, conversation_round_id: previous ? 'round-a' : 'round-b', total_tokens: previous ? 999 : 118 }] })
  })
  const activity = { id: 'round-a', status: 'SUCCEEDED', tools_used: [], cost: 0, execution_time: 1 }
  await mount(page, 'app/chat/components/AgentExecutionTrace.vue', { props: { roomId: 'room-a', activity } })
  try {
    await page.locator('.trace-summary').click()
    await expect.poll(() => requested).toBe(true)
    await page.evaluate(activity => window.testApp.setProps({ activity: { ...activity, id: 'round-b' } }), activity)
    await expect(page.locator('.trace-summary')).toHaveAttribute('aria-expanded', 'false')
    await page.locator('.trace-summary').click()
    await page.getByRole('tab', { name: 'Details', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Detailed state', exact: true })).toContainText('galaris://task/current-task')
    await expect(page.getByRole('alert')).toContainText('Usage unavailable')
  } finally { release() }
  callsFail = false
  await page.locator('.trace-summary').click()
  await page.locator('.trace-summary').click()
  await expect(page.getByRole('region', { name: 'Recorded usage', exact: true })).toContainText('118 tokens · $0.0001')
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Detailed state', exact: true })).not.toContainText('Old work')
  await expect(page.getByRole('region', { name: 'Recorded usage', exact: true })).not.toContainText('999 tokens')
})

test('execution trace remains the default and memory is opt-in even with recorded operations', async ({ page }) => {
  await mount(page, 'app/task/components/ExecutionResult.vue', { props: { executionResult: result, embedded: true } })
  const trace = page.getByRole('tab').first()
  await expect(trace).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: /memory/i })).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ showMemory: true }))
  await expect(page.getByRole('tab', { name: /memory/i })).toBeVisible()
  await expect(trace).toHaveAttribute('aria-selected', 'true')
  await page.evaluate(() => window.testApp.setProps({ showMemory: false, running: true, embedded: false, feedback: 'Working now' }))
  await expect(page.getByRole('tab', { name: /memory/i })).toHaveCount(0)
  await expect(page.getByText('Working now')).toBeVisible()
})

for (const canWrite of [true, false]) {
  test(`memory documents open the full editor in place and respect write access (${canWrite})`, async ({ page }) => {
    await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: async value => { window.copiedDocumentUrl = value } },
    }))
    const id = '00000000-0000-0000-0000-000000000123'
    let current = { ...document, id, media_type: 'text/html',
      payload: { text: '<p>Complete document body</p>' }, access: { can_read: true, can_write: canWrite } }
    const updates = []
    await jsonRoute(page, '**/api/agents?*', [agent])
    await jsonRoute(page, `**/api/memory/items/${id}?*`, { ...current, document_id: id, payload: { text: '' } })
    await page.route(`**/api/documents/${id}?*`, route => {
      if (route.request().method() === 'GET') return route.fulfill({ json: { item: current } })
      expect(route.request().method()).toBe('PATCH')
      const update = route.request().postDataJSON()
      updates.push(update)
      current = { ...current, ...update, revision: current.revision + 1, lock_version: current.lock_version + 1 }
      return route.fulfill({ json: current })
    })
    await jsonRoute(page, '**/api/memory/items/memory-a?*', { ...document, id: 'memory-a', node_kind: 'memory',
      media_type: 'text/html', payload: { text: '<p>Ordinary memory content</p>' } })
    await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
    await jsonRoute(page, '**/api/documents/keywords?*', [])
    await jsonRoute(page, '**/api/documents/folders?*', [])
    await jsonRoute(page, `**/api/documents/${id}/attachments?*`, [])
    await mount(page, 'app/task/components/ExecutionMemoryPanel.vue', { privileges: ['MEMORY_EDIT'], props: {
      agentId: 7, calls: [], context: { enabled: true, query: 'Question', count: 2, retrievedCount: 2,
        truncated: false, memoryIds: [id, 'memory-a'], error: '' },
    } })
    const originalUrl = page.url()
    await expect(page.getByText('Ordinary memory content', { exact: true })).toBeVisible()
    await expect(page.getByText('Complete document body', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Document', { exact: true })).toBeVisible()
    // Retired memory type badges are incidental; retain the editor, URL and access checks below.
    const copyUrl = page.getByRole('button', { name: 'Copy document URL', exact: true })
    await expect(copyUrl).toContainText(`document://${id}`)
    if (canWrite) await copyUrl.click()
    else await copyUrl.press('Enter')
    await expect.poll(() => page.evaluate(() => window.copiedDocumentUrl)).toBe(`document://${id}`)
    await expect(page).toHaveURL(originalUrl)
    await page.getByRole('button', { name: 'View', exact: true }).click()
    const dialog = page.getByRole('dialog')
    const title = dialog.getByLabel('Title', { exact: true })
    await expect(title).toHaveValue('Test document')
    await expect(dialog.getByText('Complete document body', { exact: true })).toBeVisible()
    if (canWrite) {
      await expect(title).toBeEditable()
      await title.fill('Edited from memory')
    } else {
      await expect(title).not.toBeEditable()
    }
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(dialog).toHaveCount(0)
    if (canWrite) await expect.poll(() => updates.length).toBe(1)
    else expect(updates).toEqual([])
    await expect(page).toHaveURL(originalUrl)
    await page.getByRole('button', { name: 'View', exact: true }).click()
    await expect(title).toHaveValue(canWrite ? 'Edited from memory' : 'Test document')
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page).toHaveURL(originalUrl)
  })
}

test('a successful round keeps its outcome when its reconstructed calls include a failed attempt', async ({ page }) => {
  await mount(page, 'app/task/components/ExecutionResult.vue', { props: {
    executionResult: null, executionSuccess: true,
    llmCalls: [{ ...call, id: 'failed-call', status: 'error' }, { ...call, id: 'successful-call', status: 'completed' }],
  } })
  const header = page.locator('.q-expansion-item__container > .q-item').first()
  await expect(header).toContainText('Success')
  await expect(header).not.toContainText('Failure')
  await page.evaluate(() => window.testApp.setProps({ executionSuccess: false }))
  await expect(header).toContainText('Failure')
  await page.evaluate(result => window.testApp.setProps({ executionSuccess: undefined, executionResult: result }), result)
  await expect(header).toContainText('Success')
})

test('a completed voice round in the message history is presented as successful', async ({ page }) => {
  await jsonRoute(page, '**/api/topics?*', { items: [], total: 0 })
  const message = { id: 'message-a', agent_id: 7, agent_name: 'Alice', channel_kind: 'chat',
    payload: { text: 'Hello' }, round_id: 'round-a', round_status: 'COMPLETED',
    response_text: 'Delivered answer', response_error: 'Obsolete attempt failure',
    created_at: call.started_at, responded_at: call.completed_at }
  const round = { id: 'round-a', agent_id: 7, agent_name: 'Alice', status: 'COMPLETED',
    rendered_input: [message.payload], response_text: message.response_text,
    last_error: message.response_error, execution_result: result, delivery_state: 'DELIVERED',
    attempt_count: 1, created_at: call.started_at, finished_at: call.completed_at,
    unknown_notifications: [], task_startup_timings: [{ task_id: 'delegated-task', label: 'Delegated work', preparation_seconds: 4 }] }
  await mount(page, 'app/conversation/components/ConversationRoundDetail.vue', { props: {
    message, round, calls: [call], loading: false, error: '', callsLoading: false, callsError: '',
  } })
  await expect(page.getByText('Delivered answer', { exact: true })).toBeVisible()
  await expect(page.locator('.conversation-detail-header')).toContainText('Completed')
  await expect(page.getByText('Obsolete attempt failure')).toHaveCount(0)
  await page.getByRole('tab', { name: 'Details', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Detailed state', exact: true })).toContainText('Completed')
  await expect(page.getByRole('region', { name: 'Initial startup', exact: true })).toContainText('galaris://task/delegated-task')
  await expect(page.getByRole('region', { name: 'Recorded usage', exact: true })).toContainText('118 tokens · $0.0001')
  await page.getByRole('tab', { name: 'Prompt', exact: true }).click()
  await expect(page.getByText('User request', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Initial startup', exact: true })).toHaveCount(0)
  await page.getByRole('tab', { name: 'Details', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Initial startup', exact: true })).toContainText('4 s')
})

test('an agent lookup failure preserves the selected value and can recover on reopening', async ({ page }) => {
  await mount(page, 'app/agent/components/AgentSelect.vue', { props: {
    modelValue: 7, label: 'Worker', loadAgents: false, options: [{ value: 7, label: 'Alice Example' }],
  } })
  const select = page.getByRole('combobox', { name: 'Worker' })
  await expect(page.locator('.q-field__native')).toContainText('Alice Example')
  await page.route('**/api/agents/selection?scope=management', route => route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } }))
  await select.click()
  await expect(page.getByText('Temporarily unavailable', { exact: false })).toBeVisible()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue'))).toEqual([])
  await page.keyboard.press('Escape')
  await jsonRoute(page, '**/api/agents/selection?scope=management', [{ id: 7, label: 'Alice Example', has_avatar: false }])
  await select.click()
  await expect(page.getByRole('option', { name: 'Alice Example', exact: true })).toBeVisible()
  await expect(page.getByText('Temporarily unavailable', { exact: false })).toHaveCount(0)
})

for (const component of ['LlmCall', 'LlmCallTaskDetail']) {
  test(`${component} renders semantic purpose, effort, output tokens and billed cost`, async ({ page }) => {
    await jsonRoute(page, '**/api/llm-providers/llms', [])
    await mount(page, `app/llm/components/${component}.vue`, { props: { call, taskColor: { name: 'primary', hex: '#1976d2' } } })
    await expect(page.locator('.reasoning-effort-badge')).toContainText('High')
    await expect(page.locator('.llm-purpose-badge')).not.toHaveText('')
    const tokens = page.locator('.q-badge[title]').filter({ has: page.locator('.q-icon', { hasText: 'title' }) })
    await expect(tokens).toContainText('17')
    await expect(tokens).toHaveAttribute('title', /101[\s\S]*23[\s\S]*17/)
    const cost = page.locator('.q-badge').filter({ has: page.locator('.q-icon', { hasText: 'attach_money' }) })
    await expect(cost).toContainText('0.000123')
    await expect(cost).not.toContainText('0.000456')
    await expect(cost).toHaveAttribute('title', /0\.000456/)
    await page.evaluate(call => window.testApp.setProps({ call: { ...call, inference_cost: call.cost, reasoning_effort: null } }), call)
    await expect(cost).not.toHaveAttribute('title', /0\.000456/)
    await expect(page.locator('.reasoning-effort-badge')).toHaveCount(0)
  })
}

test('LLM detail switches between real editors and normalized terminal response', async ({ page }) => {
  await mount(page, 'app/llm/components/LlmCallDetails.vue', { props: { call } })
  await page.getByRole('tab', { name: /^.*response/i }).click()
  const editor = page.locator('textarea.code-editor')
  await expect(editor).toHaveValue(/Final answer/)
  await expect(editor).toHaveValue(/output_tokens/)
  await expect(editor).not.toHaveValue(/PRIVATE RAW TRANSPORT/)
  await expect(editor).not.toBeEditable()
  await page.getByRole('tab', { name: /^.*system prompt/i }).click()
  await expect(page.getByRole('textbox', { name: 'Markdown', exact: true })).toHaveValue('System instructions')
})

test('task call stream keeps agent process calls, excludes unrelated ownership and handles deletion', async ({ page }) => {
  await jsonRoute(page, '**/api/llm-providers/llms', [])
  await jsonRoute(page, '**/api/llm-calls?task_id=task-a', [])
  await mount(page, 'app/llm/components/LlmCalls.vue', { props: { taskId: 'task-a' } })
  for (const item of [
    { ...call, id: 'owned', task_id: 'task-a', process_run_id: 'process-a', purpose: 'agent.execution' },
    { ...call, id: 'process', task_id: 'task-a', process_run_id: 'process-a', purpose: 'process.analysis' },
    { ...call, id: 'foreign', task_id: 'task-b' },
  ]) await page.evaluate(item => window.testApp.emitSocket('llm_call.create', { data: item }), item)
  await expect(page.locator('.llm-call-list > *')).toHaveCount(1)
  await page.evaluate(() => window.testApp.emitSocket('llm_call.delete', { data: { id: 'owned' } }))
  await expect(page.locator('.llm-call-list')).toHaveCount(0)
})

test('task overview mouse and keyboard filters send mutually exclusive server parameters', async ({ page }) => {
  const requests = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/topics?*', { items: [], total: 0 })
  await page.route('**/api/tasks/recent?*', route => {
    requests.push(new URL(route.request().url()).searchParams.toString())
    return route.fulfill({ json: { items: [], total: 0, has_more: false, summary: { running: 2, completed: 3, paused: 1, errors: 1 } } })
  })
  await mount(page, 'app/task/pages/index.vue', { route: '/task?tab=tasks' })
  for (const [label, interaction, parameter] of [['Paused', 'click', 'paused_only'], ['Running', 'Enter', 'active'], ['Errors', 'Space', 'errors_only']]) {
    const metric = page.getByRole('button', { name: new RegExp(`^${label}\\b`) })
    if (interaction === 'click') await metric.click()
    else await metric.press(interaction)
    await expect(metric).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('button', { pressed: true })).toHaveCount(1)
    await expect.poll(() => requests.at(-1)).toContain(`${parameter}=true`)
    for (const other of ['paused_only', 'active', 'errors_only'].filter(value => value !== parameter)) expect(requests.at(-1)).not.toContain(`${other}=true`)
  }
})

test('process detail exposes terminal-safe actions and persisted usage and purpose', async ({ page }) => {
  const run = { id: 'run-a', status: 'running', summary: 'Sample process', input: {}, output: {}, engine_metadata: {}, events: [], llm_calls: [call] }
  await mount(page, 'app/process/components/ProcessRunDetailContent.vue', { props: { run, analysis: null, canOperateRuns: true, canAnalyze: true, canAdmin: true, canReadTasks: false } })
  await expect(page.getByRole('button', { name: /delete/i })).toBeDisabled()
  await expect(page.getByRole('button', { name: /^cancel$/i })).toBeVisible()
  await expect(page.locator('.process-llm-metrics .q-badge').first()).toHaveAttribute('title', /101[\s\S]*23[\s\S]*17/)
  await page.evaluate(run => window.testApp.setProps({ run: { ...run, status: 'error' } }), run)
  await expect(page.getByRole('button', { name: /delete/i })).toBeEnabled()
  await expect(page.getByRole('button', { name: /^cancel$/i })).toHaveCount(0)
  await page.getByRole('button', { name: /retry/i }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.name)).toBe('retry')
})
