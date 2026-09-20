import { test, expect, mount, jsonRoute } from './fixtures.mjs'

async function conversation(page) {
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
    await page.route(`**/api/chat/rooms/${room.id}/messages?*`, route => route.fulfill({
      json: { items: [messages[room.id]], total: 1, page: 1 },
    }))
    await jsonRoute(page, `**/api/chat/rooms/${room.id}/read`, {})
    await jsonRoute(page, `**/api/chat/rooms/${room.id}/commands`, { commands: [] })
    await jsonRoute(page, `**/api/chat/rooms/${room.id}/speech/status*`, { available_agent_ids: [] })
  }
  await jsonRoute(page, '**/api/chat/inbox', { unread_count: 0 })
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  await jsonRoute(page, '**/api/chat/agents/7/avatar', {})
  await mount(page, 'app/chat/pages/index.vue', { route: '/chat?room=room-a', privileges: ['CHAT_SEND'] })
  await expect(page.locator('.conversation-pane')).toContainText('Content room-a')
  return { rooms, messages }
}

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

for (const status of [403, 404]) {
  test(`a late ${status} from a previous room cannot clear the current conversation`, async ({ page }) => {
    await conversation(page)
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
