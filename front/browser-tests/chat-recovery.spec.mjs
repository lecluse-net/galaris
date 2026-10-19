import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document as documentFixture } from './data.mjs'

async function conversation(page, privileges = ['CHAT_SEND'], commandsHandler = null, activityHandler = null) {
  const rooms = ['a', 'b'].map(code => ({ id: `room-${code}`, label: `Conversation ${code}`,
    agent_id: 7, agent_name: 'Alice', agent_active: false, source: null, writable: true,
    members: [], muted: false, archived: false, unread_count: 0, conversation_type: 'text' }))
  const messages = Object.fromEntries(rooms.map(room => [room.id, {
    id: `message-${room.id}`, external_id: `external-${room.id}`, room_id: room.id,
    text: `Content ${room.id}`, files: [], sender: null, direction: 'inbound',
    created_at: '2026-09-01T12:00:00Z', is_mine: true, status: 'sent',
  }]))
  await jsonRoute(page, '**/api/chat/status', { enabled: true, chat_enabled: true, max_attachment_bytes: 1000000 })
  await jsonRoute(page, '**/api/chat/rooms?*', { items: rooms, total: rooms.length })
  for (const room of rooms) {
    await jsonRoute(page, `**/api/chat/rooms/${room.id}`, room)
    await jsonRoute(page, `**/api/chat/rooms/${room.id}/activity?*`, { items: [], total: 0 })
    if (activityHandler) await page.route(`**/api/chat/rooms/${room.id}/activity?*`, activityHandler)
    await page.route(`**/api/chat/rooms/${room.id}/messages?*`, route => route.fulfill({
      json: { items: [messages[room.id]], total: 1, page: 1 },
    }))
    await jsonRoute(page, `**/api/chat/rooms/${room.id}/read`, {})
    await jsonRoute(page, `**/api/chat/rooms/${room.id}/commands`, { commands: [] })
    if (commandsHandler) await page.route(`**/api/chat/rooms/${room.id}/commands`, commandsHandler)
    await jsonRoute(page, `**/api/chat/rooms/${room.id}/speech/status*`, { available_agent_ids: [] })
  }
  await jsonRoute(page, '**/api/chat/inbox', { unread_count: 0 })
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  await jsonRoute(page, '**/api/chat/agents/7/avatar', {})
  await mount(page, 'app/chat/pages/index.vue', { route: '/chat?room=room-a', privileges })
  await expect(page.locator('.conversation-pane')).toContainText('Content room-a')
  return { rooms, messages }
}

test('messages and composer remain usable while optional commands are slow or unavailable', async ({ page }) => {
  const releases = []
  const state = await conversation(page, ['CHAT_SEND'], async route => {
    await new Promise(resolve => releases.push(resolve))
    await route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } })
  })
  await expect.poll(() => releases.length).toBeGreaterThan(0)
  const composer = page.locator('.composer-shell textarea')
  await composer.fill('A draft while commands are loading')
  state.messages['room-a'].text = 'Content room-a updated while commands are pending'
  for (let index = 0; index < 5; index++) {
    await refresh(page, `optional-${index}`)
    await settled(page, `optional-${index}`)
  }
  await expect(page.locator('.conversation-pane')).toContainText('Content room-a updated while commands are pending')
  expect(releases).toHaveLength(1)
  releases.forEach(release => release())
  await expect(page.locator('.conversation-pane')).toContainText('Content room-a')
  await expect(composer).toHaveValue('A draft while commands are loading')
})

async function refresh(page, key, method = 'refreshSelected') {
  await page.evaluate(async ({ key, method }) => {
    const { useChatStore } = await import('/app/chat/stores/chat.ts')
    window.refreshResults ??= {}
    void useChatStore(window.testApp.pinia)[method]().then(
      () => { window.refreshResults[key] = 'done' },
      () => { window.refreshResults[key] = 'error' },
    )
  }, { key, method })
}

async function settled(page, key) {
  await expect.poll(() => page.evaluate(key => window.refreshResults[key], key)).toBeTruthy()
}

test('conversation activity bursts retain new messages without concurrent history reloads', async ({ page }) => {
  const state = await conversation(page)
  let release, requests = 0, active = 0, peak = 0
  const blocked = new Promise(resolve => { release = resolve })
  await page.route('**/api/chat/rooms/room-a/messages?*', async route => {
    const items = [{ ...state.messages['room-a'] }]
    requests++; peak = Math.max(peak, ++active)
    try {
      if (requests === 1) await blocked
      await route.fulfill({ json: { items, total: items.length, page: 1 } })
    } finally { active-- }
  })
  const signal = () => page.evaluate(() => window.testApp.emitSocket('chat.activity', {
    data: { room_id: 'room-a' },
  }))
  await signal()
  await expect.poll(() => requests).toBe(1)
  state.messages['room-a'].text = 'Content received during activity burst'
  await page.evaluate(() => {
    for (let index = 0; index < 30; index++) window.testApp.emitSocket('chat.activity', {
      data: { room_id: 'room-a' },
    })
  })
  const composer = page.locator('.composer-shell textarea')
  await composer.fill('Draft preserved during refresh')
  release()
  await expect(page.locator('.conversation-pane')).toContainText('Content received during activity burst')
  await expect(composer).toHaveValue('Draft preserved during refresh')
  expect(peak).toBe(1)
  expect(requests).toBe(2)
})

test('opening a conversation retains its running response when history refresh overlaps the initial activity', async ({ page }) => {
  let releaseActivity
  const opening = conversation(page, ['CHAT_SEND'], null, async route => {
    await new Promise(resolve => { releaseActivity = resolve })
    await route.fulfill({ json: {
      items: [{ id: 'synthetic-running-round', status: 'RUNNING', attempt: 1,
        created_at: '2026-09-01T12:01:00Z' }], total: 1,
      runtime: { round_id: 'synthetic-running-round', kind: 'snapshot', sequence: 1, attempt: 1,
        result: { prompt: '', system_prompt: '', messages: [{ type: 'text', content: 'Synthetic restored response' }],
          result: 'Synthetic restored response', success: true, execution_time: 0, cost: 0, tools_used: [], metadata: {} } },
    } })
  })
  await expect.poll(() => typeof releaseActivity).toBe('function')
  await refresh(page, 'overlapping-history', 'loadRecentMessages')
  await settled(page, 'overlapping-history')
  releaseActivity()
  await opening
  await expect(page.locator('.message-bubble--live')).toContainText('Synthetic restored response')
})

test('an admitted round is visible before streaming and keeps its response through startup', async ({ page }) => {
  await conversation(page)
  await jsonRoute(page, '**/api/chat/rooms/room-a/activity?*', {
    items: [{ id: 'admitted-round', status: 'FROZEN', created_at: '2026-09-01T12:01:00Z' }],
    total: 1,
  })
  await page.evaluate(() => window.testApp.emitSocket('chat.activity', {
    data: { room_id: 'room-a', round_id: 'admitted-round' },
  }))
  const response = page.locator('.message-bubble--live')
  await expect(response.getByRole('button', { name: /^Thinking/ })).toBeVisible()
  await expect(response).toHaveCount(1)

  await page.evaluate(() => {
    const emit = event => window.testApp.emitSocket('chat.runtime', {
      data: { room_id: 'room-a', round_id: 'admitted-round', ...event },
    })
    emit({ kind: 'started', sequence: 0 })
    emit({ kind: 'message', sequence: 1, message: { type: 'text', content: 'Synthetic ' } })
  })
  // A useful prefix must be visible while the round is still running.
  await expect(response).toContainText('Synthetic')
  await expect(response.getByRole('button', { name: /^Thinking/ })).toBeVisible()
  await page.evaluate(() => window.testApp.emitSocket('chat.runtime', { data: {
    room_id: 'room-a', round_id: 'admitted-round', kind: 'message', sequence: 2,
    message: { type: 'text', content: 'answer' },
  } }))
  await expect(response).toContainText('Synthetic answer')
  await page.evaluate(() => window.testApp.emitSocket('chat.runtime', { data: {
    room_id: 'room-a', round_id: 'admitted-round', kind: 'finished', sequence: 3, success: true,
  } }))
  await expect(response).toHaveCount(1)
  await expect(response).toContainText('Synthetic answer')
  await expect(page.locator('.conversation-pane')).toContainText('Content room-a')
})

test('stopping removes the agent response through late events and reopening, while a refused stop preserves it', async ({ page }, testInfo) => {
  await conversation(page)
  let activity = { id: 'stopped-round', status: 'RUNNING', attempt: 1,
    available_actions: ['pause', 'stop', 'respond'], control_action: null,
    response_message_id: null, message_ids: ['message-room-a'], tools_used: [],
    created_at: '2026-09-01T12:01:00Z' }
  await page.route('**/api/chat/rooms/room-a/activity?*', route => route.fulfill({
    json: { items: [activity], total: 1 },
  }))
  await refresh(page, 'running')
  await settled(page, 'running')
  const emit = event => page.evaluate(event => window.testApp.emitSocket('chat.runtime', {
    data: { room_id: 'room-a', round_id: 'stopped-round', attempt: 1, ...event },
  }), event)
  await emit({ kind: 'started', sequence: 0 })
  await emit({ kind: 'message', sequence: 1, message: { type: 'text', content: 'Unfinished answer' } })
  const response = page.locator('.message-bubble--live')
  await expect(response).toContainText('Unfinished answer')
  let commands = 0
  await page.route('**/api/chat/rooms/room-a/activity/stopped-round/control', route => {
    expect(route.request().postDataJSON()).toEqual({ action: 'stop', expected_attempt: 1 })
    commands += 1
    if (commands === 1) return route.fulfill({ status: 409, json: { detail: 'Synthetic stop refused' } })
    activity = { ...activity, control_action: 'stop', available_actions: [] }
    return route.fulfill({ json: { round_id: activity.id, status: activity.status, control_action: 'stop' } })
  })
  const stop = page.getByRole('button', { name: 'Stop response', exact: true })
  await stop.click()
  await expect(page.getByRole('alert')).toContainText('Synthetic stop refused')
  await expect(response).toContainText('Unfinished answer')
  await expect(stop).toBeEnabled()
  await stop.focus()
  await page.keyboard.press('Enter')
  await expect(response).toHaveCount(0)
  await expect(page.locator('.message-timeline')).toContainText('Content room-a')
  await emit({ kind: 'message', sequence: 2, message: { type: 'text', content: 'Late fragment' } })
  await expect(response).toHaveCount(0)
  activity = { ...activity, status: 'CANCELLED', control_action: null, available_actions: ['restart'] }
  await emit({ kind: 'finished', sequence: 3, success: false })
  await expect.poll(() => page.evaluate(async () => {
    const { useChatStore } = await import('/app/chat/stores/chat.ts')
    return useChatStore(window.testApp.pinia).activity[0]?.status
  })).toBe('CANCELLED')
  await mount(page, 'app/chat/pages/index.vue', { route: '/chat?room=room-a', privileges: ['CHAT_SEND'] })
  await expect(page.locator('.conversation-pane')).toContainText('Content room-a')
  await expect(page.locator('.message-row')).toHaveCount(1)
  await expect(page.getByText('Unfinished answer')).toHaveCount(0)
  await expect(page.getByText('Response stopped', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('stopped-response-removed.png'), fullPage: true })
})

test('an intervention shows rewriting before HTTP catches up and the successor retains real errors', async ({ page }) => {
  const state = await conversation(page)
  const result = { prompt: '', system_prompt: '', messages: [], result: '', success: true,
    execution_time: 0, cost: 0, tools_used: [], metadata: {} }
  const emit = event => page.evaluate(event => window.testApp.emitSocket('chat.runtime', {
    data: { room_id: 'room-a', ...event },
  }), event)
  await emit({ round_id: 'draft-round', kind: 'started', sequence: 0 })
  await emit({ round_id: 'draft-round', kind: 'message', sequence: 1,
    message: { type: 'text', content: 'Provisional response' } })
  const response = page.locator('.message-bubble--live')
  await expect(response).toContainText('Provisional response')

  let release
  const pending = new Promise(resolve => { release = resolve })
  let submitted = false
  await page.route('**/api/chat/rooms/room-a/messages', route => {
    const { text } = route.request().postDataJSON()
    state.messages['room-a'] = { ...state.messages['room-a'], id: 'context-message',
      external_id: 'context-message', text }
    submitted = true
    return route.fulfill({ json: state.messages['room-a'] })
  })
  const successor = { round_id: 'successor-round', kind: 'snapshot', sequence: 1,
    result: { ...result, messages: [{ type: 'text', content: 'Updated response' }] } }
  await page.route('**/api/chat/rooms/room-a/activity?*', async route => {
    await pending
    await route.fulfill({ json: { items: [{ id: 'successor-round', status: 'RUNNING',
      tools_used: [], created_at: '2026-09-01T12:01:00Z' }], total: 1, runtime: successor } })
  })
  try {
    await page.locator('.composer-shell textarea').fill('Adapt to the new context')
    await page.getByRole('button', { name: 'Post', exact: true }).click()
    await expect.poll(() => submitted).toBe(true)
    await emit({ round_id: 'draft-round', kind: 'finished', sequence: 2, success: false,
      result: { ...result, success: false, metadata: { interrupted_by_new_input: true } } })
    await expect(response.getByRole('button', { name: /^Rewriting response/ })).toBeVisible()
    await expect(page.getByText('The execution encountered a problem')).toHaveCount(0)
    await page.screenshot({ path: test.info().outputPath('rewriting-in-chat.png') })
  } finally { release() }
  await expect(response).toContainText('Updated response')
  await expect(response.getByRole('button', { name: /^Thinking/ })).toBeVisible()
  await emit({ round_id: 'successor-round', kind: 'finished', sequence: 2, success: false,
    result: { ...result, success: false } })
  await expect(response.getByRole('button', { name: /^The execution encountered a problem/ })).toBeVisible()
  await expect(page.getByText('Rewriting response…')).toHaveCount(0)
})

for (const width of [1280, 390]) {
  test(`conversation header toggles all filters and creates a conversation at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const agents = [{ agent_id: 7, display_name: 'Alice', has_avatar: false }]
    await jsonRoute(page, '**/api/chat/viewer-agents', agents)
    await jsonRoute(page, '**/api/chat/recipients?*', { agents, total: agents.length })
    await conversation(page, ['CHAT_SEND', 'CHAT_MANAGE', 'CHAT_IMPERSONATE'])
    if (width < 1024) await page.getByRole('button', { name: 'Details', exact: true }).click()
    const header = page.locator('.sidebar-accordion-header').filter({ hasText: 'Conversations' })
    const toggle = header.getByRole('button', { name: 'Conversation display options', exact: true })
    const search = page.getByRole('textbox', { name: 'Search conversations…', exact: true })
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await expect(search).toBeHidden()
    await toggle.click()
    await expect(search).toBeVisible()
    await expect(page.locator('.viewer-select')).toBeVisible()
    await expect(page.getByRole('checkbox')).toHaveCount(2)
    await page.getByRole('checkbox', { name: 'Show archived conversations' }).click()
    await expect(page.getByRole('checkbox', { name: 'Show archived conversations' })).toBeChecked()
    await jsonRoute(page, '**/api/chat/rooms?*', { items: [], total: 0 })
    await search.fill('No matching conversation')
    await expect(page.locator('.room-item')).toHaveCount(0)
    await expect(search).toBeVisible()
    await toggle.click()
    await expect(search).toBeHidden()
    await toggle.click()
    await expect(search).toHaveValue('No matching conversation')
    await expect(page.getByRole('checkbox', { name: 'Show archived conversations' })).toBeChecked()
    await page.screenshot({ path: testInfo.outputPath('conversation-filters.png'), fullPage: true })
    await toggle.click()
    await header.getByRole('button', { name: 'New conversation with an agent', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByRole('combobox', { name: 'Agent', exact: true })).toBeVisible()
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })
}

for (const section of [
  { path: 'documents', label: 'Documents', privilege: 'MEMORY_ACCESS', event: 'memory.update',
    item: { id: 'doc-a', label: 'Available document', uri: 'document://doc-a', revision: 1 } },
  { path: 'tasks', label: 'Tasks', privilege: 'TASK_ACCESS', event: 'task.update',
    item: { id: 'task-a', label: 'Available task', status: 'SUCCESS', agent_id: null, data: {}, revision: 1,
      tree_parent_id: null, created_at: '2026-09-01T12:00:00Z' } },
  { path: 'processes', label: 'Processes', privilege: 'PROCESS_READ', event: 'process_run.update',
    item: { id: 'process-a', process_label: 'Available process', status: 'success', created_at: '2026-09-01T12:00:00Z' } },
]) {
  test(`${section.path} expand with content, preserve manual collapse and reset on room changes`, async ({ page }) => {
    let items = []
    let reads = 0
    await page.route(`**/api/chat/rooms/room-a/${section.path}?*`, route => {
      reads += 1
      return route.fulfill({ json: { items, total: items.length, page: 1, page_size: 50 } })
    })
    await jsonRoute(page, `**/api/chat/rooms/room-b/${section.path}?*`, { items: [], total: 0 })
    await jsonRoute(page, '**/api/chat/recipients?*', { agents: [], total: 0 })
    await jsonRoute(page, '**/api/tasks/activity', [])
    await jsonRoute(page, /\/api\/memory\/documents\/doc-a(?:\?.*)?$/, { item: documentFixture, agent_id: 7 })
    await conversation(page, ['CHAT_SEND', section.privilege])
    const header = page.locator('.sidebar-accordion-header').filter({ hasText: section.label })
    await expect.poll(() => reads).toBeGreaterThan(0)
    await expect(header).toHaveAttribute('aria-expanded', 'false')
    const refreshSection = async () => {
      const previous = reads
      await page.evaluate(event => window.testApp.emitSocket(event, { data: {} }), section.event)
      await expect.poll(() => reads).toBeGreaterThan(previous)
    }
    items = [section.item]
    await refreshSection()
    await expect(header).toHaveAttribute('aria-expanded', 'true')
    await header.click()
    await refreshSection()
    await expect(header).toHaveAttribute('aria-expanded', 'false')
    await header.click()
    items = []
    await refreshSection()
    await expect(header).toHaveAttribute('aria-expanded', 'false')
    items = [section.item]
    await refreshSection()
    await expect(header).toHaveAttribute('aria-expanded', 'true')
    await page.evaluate(() => window.testApp.navigate('/chat?room=room-b'))
    await expect(page.locator('.conversation-pane')).toContainText('Content room-b')
    await expect(header).toHaveAttribute('aria-expanded', 'false')
  })
}

for (const status of [403, 404]) {
  test(`a late ${status} from a previous room cannot clear the current conversation`, async ({ page }) => {
    await conversation(page)
    const currentRoom = page.locator('.conversation-list [aria-current="true"]')
    await expect(currentRoom).toHaveCount(1)
    await expect(currentRoom).toContainText('Conversation a')
    let release
    await page.route('**/api/chat/rooms/room-a', async route => {
      await new Promise(resolve => { release = resolve })
      await route.fulfill({ status, json: { detail: 'Access no longer available' } })
    })
    await refresh(page, 'old')
    await expect.poll(() => Boolean(release)).toBe(true)
    await page.evaluate(() => window.testApp.navigate('/chat?room=room-b'))
    await expect(page.locator('.conversation-pane')).toContainText('Content room-b')
    release()
    await settled(page, 'old')
    await expect(page.locator('.conversation-pane')).toContainText('Content room-b')
    await expect(currentRoom).toHaveCount(1)
    await expect(currentRoom).toContainText('Conversation b')
    await expect(page.locator('.composer-fields textarea')).toBeEditable()
  })
}

test('an older HTTP projection cannot overwrite a newer accepted message', async ({ page }) => {
  const state = await conversation(page)
  let release
  await page.route('**/api/chat/rooms/room-a/activity?*', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { items: [], total: 0 } })
  }, { times: 1 })
  await refresh(page, 'old')
  await expect.poll(() => Boolean(release)).toBe(true)
  state.messages['room-a'].text = 'Current authoritative content'
  await refresh(page, 'new')
  await settled(page, 'new')
  await expect(page.locator('.conversation-pane')).toContainText('Current authoritative content')
  release()
  await settled(page, 'old')
  await expect(page.locator('.conversation-pane')).toContainText('Current authoritative content')
})

test('a current access denial still removes protected conversation content', async ({ page }) => {
  await conversation(page)
  await jsonRoute(page, '**/api/chat/rooms?*', { items: [], total: 0 })
  await page.route('**/api/chat/rooms/room-a', route => route.fulfill({ status: 403, json: { detail: 'Revoked' } }))
  await refresh(page, 'denied')
  await settled(page, 'denied')
  await expect(page.getByText('Content room-a', { exact: true })).toHaveCount(0)
})

test('a failed newer refresh does not discard an otherwise valid pending response', async ({ page }) => {
  const state = await conversation(page)
  state.messages['room-a'].text = 'Recovered authoritative content'
  let release
  await page.route('**/api/chat/rooms/room-a/activity?*', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { items: [], total: 0 } })
  }, { times: 1 })
  await refresh(page, 'pending')
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.route('**/api/chat/rooms/room-a/messages?*', route => route.fulfill({
    status: 503, json: { detail: 'Temporarily unavailable' },
  }), { times: 1 })
  await refresh(page, 'failed')
  await settled(page, 'failed')
  release()
  await settled(page, 'pending')
  await expect(page.locator('.conversation-pane')).toContainText('Recovered authoritative content')
})

test('a superseded room-list denial cannot clear an authorized conversation', async ({ page }) => {
  await conversation(page)
  let release
  await page.route('**/api/chat/rooms?*', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ status: 403, json: { detail: 'Old scope' } })
  }, { times: 1 })
  await refresh(page, 'old-list', 'loadRooms')
  await expect.poll(() => Boolean(release)).toBe(true)
  await refresh(page, 'new-list', 'loadRooms')
  await settled(page, 'new-list')
  release()
  await settled(page, 'old-list')
  await expect(page.locator('.conversation-pane')).toContainText('Content room-a')
})

test('a denied history page from the previous room cannot clear the new selection', async ({ page }) => {
  const state = await conversation(page)
  await jsonRoute(page, '**/api/chat/rooms/room-a/messages?*', {
    items: [state.messages['room-a']], total: 100, page: 1,
  })
  await refresh(page, 'history-ready')
  await settled(page, 'history-ready')
  let release
  await page.route('**/api/chat/rooms/room-a/messages?*', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ status: 403, json: { detail: 'Old scope' } })
  })
  await refresh(page, 'history', 'loadOlderMessages')
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.evaluate(() => window.testApp.navigate('/chat?room=room-b'))
  await expect(page.locator('.conversation-pane')).toContainText('Content room-b')
  release()
  await settled(page, 'history')
  await expect(page.locator('.conversation-pane')).toContainText('Content room-b')
})

for (const switchRoom of [false, true]) {
  test(`a stream gap remains recoverable while another projection is pending (switch room: ${switchRoom})`, async ({ page }) => {
    await conversation(page)
    const target = switchRoom ? 'room-b' : 'room-a'
    const runtime = { room_id: target, round_id: 'new-round', kind: 'snapshot', sequence: 3,
      result: { prompt: '', messages: [{ type: 'text', content: 'Recovered live response' }],
        result: '', success: true, execution_time: 0, cost: 0, tools_used: [] } }
    const gap = room_id => page.evaluate(room_id => window.testApp.emitSocket('chat.runtime', {
      data: { room_id, round_id: 'new-round', kind: 'message', sequence: 3,
        message: { type: 'text', content: 'missing delta' } },
    }), room_id)
    let release
    await page.route('**/api/chat/rooms/room-a/activity?*', async route => {
      await new Promise(resolve => { release = resolve })
      await route.fulfill({ json: { items: [], total: 0 } })
    }, { times: 1 })
    await gap('room-a')
    await expect.poll(() => Boolean(release)).toBe(true)
    if (switchRoom) {
      await page.evaluate(() => window.testApp.navigate('/chat?room=room-b'))
      await expect(page.locator('.conversation-pane')).toContainText('Content room-b')
    }
    await jsonRoute(page, `**/api/chat/rooms/${target}/activity?*`, {
      items: [{ id: 'new-round', status: 'RUNNING', created_at: '2026-09-01T12:01:00Z' }], total: 1, runtime,
    })
    await gap(target)
    if (!switchRoom) release()
    try {
      await expect(page.locator('.conversation-pane')).toContainText('Recovered live response')
    } finally {
      release()
    }
  })
}
