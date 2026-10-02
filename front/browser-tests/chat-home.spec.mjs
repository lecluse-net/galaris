import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const agent = { agent_id: 7, connection_id: 1, code: 'alice', display_name: 'Alice', active: true, suggested_room_label: 'Alice (3)' }
const otherAgent = { agent_id: 8, connection_id: 2, code: 'alexandrine', display_name: 'Alexandrine Montclair', active: true, suggested_room_label: 'Alexandrine Montclair' }
const message = { id: 'message-a', room_id: 'room-a', text: 'Here is the outline for your next project.', files: [], sender: null, created_at: '2026-09-25T14:30:00Z', is_mine: false, status: 'sent' }
const room = { id: 'room-a', label: 'Project outline', agent_id: 7, agent_name: 'Alice', agent_active: false, source: null, writable: true, members: [], muted: false, archived: false, unread_count: 2, conversation_type: 'text', show_last_message: true, last_message: message }

async function home(page, options = {}) {
  await page.clock.install({ time: new Date('2026-10-02T12:00:00Z') })
  const rooms = options.rooms ?? [room, { ...room, id: 'private', label: 'Private exchange', show_last_message: false, unread_count: 0, last_message: { ...message, text: 'Hidden preview' } }, { ...room, id: 'empty', label: 'New ideas', unread_count: 0, last_message: null }]
  const requests = []
  const created = []
  const recipientRequests = []
  const agents = options.agents ?? [agent, otherAgent]
  await jsonRoute(page, '**/api/auth/me/help-dismissals', ['chat'])
  await jsonRoute(page, '**/api/chat/status', { enabled: true, chat_enabled: true, max_attachment_bytes: 1000000 })
  let recipientAttempts = 0
  await page.route('**/api/chat/recipients?*', route => {
    recipientAttempts += 1
    const params = new URL(route.request().url()).searchParams
    recipientRequests.push(Object.fromEntries(params))
    const size = Number(params.get('page_size') ?? agents.length)
    const start = (Number(params.get('page') ?? 1) - 1) * size
    return options.failRecipients && recipientAttempts === 1
      ? route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } })
      : route.fulfill({ json: { agents: agents.slice(start, start + size), total: agents.length } })
  })
  await jsonRoute(page, '**/api/agents/selection?scope=dialogue', agents.map(item => ({ id: item.agent_id, label: item.display_name, has_avatar: false })))
  await page.route('**/api/chat/agents/*/avatar', route => route.fulfill({ status: 404 }))
  await page.route('**/api/chat/rooms?*', route => {
    const params = new URL(route.request().url()).searchParams
    requests.push(Object.fromEntries(params))
    const cutoff = params.has('recent_days') ? Date.parse('2026-10-02T12:00:00Z') - Number(params.get('recent_days')) * 86400000 : null
    const items = rooms.filter(item => item.label.toLowerCase().includes((params.get('search') ?? '').toLowerCase())
      && (cutoff === null || (item.last_message && Date.parse(item.last_message.created_at) >= cutoff)))
    const currentPage = Number(params.get('page') ?? 1)
    const size = Number(params.get('page_size') ?? 50)
    return route.fulfill({ json: { items: items.slice((currentPage - 1) * size, currentPage * size), total: items.length, page: currentPage, page_size: size } })
  })
  await page.route('**/api/chat/rooms', route => {
    created.push(route.request().postDataJSON())
    return route.fulfill({ json: { ...room, label: created.at(-1).label } })
  })
  await jsonRoute(page, '**/api/chat/rooms/room-a', room)
  await jsonRoute(page, '**/api/chat/rooms/room-a/messages?*', { items: [message], total: 1 })
  await jsonRoute(page, '**/api/chat/rooms/room-a/activity?*', { items: [], total: 0 })
  await jsonRoute(page, '**/api/chat/rooms/room-a/commands', { commands: [] })
  await jsonRoute(page, '**/api/chat/rooms/room-a/read', {})
  await jsonRoute(page, '**/api/chat/rooms/room-a/speech/status*', { available_agent_ids: [] })
  await jsonRoute(page, '**/api/chat/inbox', { unread_count: 0 })
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  await mount(page, 'app/chat/pages/index.vue', { route: '/chat', privileges: options.privileges ?? ['CHAT_MANAGE', 'CHAT_SEND'], dark: options.dark ?? false })
  await expect(page.getByRole('heading', { name: 'Recent conversations' })).toBeVisible()
  return { requests, created, recipientRequests }
}

for (const width of [390, 1440]) {
  test(`chat home resumes private and dated conversations and creates with the chosen agent at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await home(page)
    await expect(page.getByRole('heading', { name: 'Who would you like to talk to?' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'New conversation', exact: true })).toHaveCount(0)
    await expect(page.getByText('Hidden preview')).toHaveCount(0)
    const recent = page.getByRole('button', { name: /Project outline Alice/ })
    await expect(recent.locator('time')).toHaveAttribute('datetime', message.created_at)
    await expect(recent.locator('time')).toContainText('2026')
    await expect(recent.getByLabel('2 unread messages')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('chat-home-light.png'), fullPage: true, animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath('chat-home-dark.png'), fullPage: true, animations: 'disabled' })
    await recent.click()
    await expect(page.locator('.conversation-pane')).toContainText(message.text)
    await expect(page.getByRole('heading', { name: 'Who would you like to talk to?' })).toHaveCount(0)

    // Remount through the real page entry to return to the welcome screen.
    const state = await home(page)
    await page.getByRole('button', { name: 'New conversation with Alice', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Conversation name', exact: true })).toHaveValue('Alice (3)')
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await page.getByRole('button', { name: 'New conversation with Alice', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Conversation name', exact: true })).toHaveValue('Alice (3)')
    await page.getByRole('textbox', { name: 'Conversation name', exact: true }).fill('A fresh project')
    await page.getByRole('button', { name: 'Chat', exact: true }).click()
    await expect(page.locator('.conversation-pane')).toContainText(message.text)
    expect(state.created).toEqual([{ agent_id: 7, label: 'A fresh project', topic_id: null, show_last_message: true }])
  })
}

test('chat home keeps search and filters visible without creation privileges', async ({ page }) => {
  const { requests } = await home(page, { privileges: [] })
  await expect(page.getByRole('button', { name: /New conversation/ })).toHaveCount(0)
  await page.getByRole('textbox', { name: 'Search conversations…' }).fill('missing')
  await expect(page.getByText('No conversations to display.')).toBeVisible()
  await page.getByRole('textbox', { name: 'Search conversations…' }).fill('Project')
  await expect(page.getByText('Project outline', { exact: true })).toBeVisible()
  await page.getByRole('checkbox', { name: 'Show archived conversations' }).click()
  await expect(page.getByRole('checkbox', { name: 'Show archived conversations' })).toBeChecked()
  await expect.poll(() => requests.at(-1)?.include_archived).toBe('true')
  await expect.poll(() => requests.at(-1)?.search).toBe('Project')
})

for (const count of [50, 51, 1000]) {
  test(`home paginates ${count} agents and conversations independently`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 })
    const agents = Array.from({ length: count }, (_, index) => ({ ...agent, agent_id: index + 1, display_name: `Agent ${index + 1}`, suggested_room_label: `Agent ${index + 1} (2)` }))
    const rooms = Array.from({ length: count }, (_, index) => ({ ...room, id: `room-${index + 1}`, label: `Conversation ${index + 1}` }))
    const state = await home(page, { agents, rooms })
    const agentPages = page.getByRole('navigation', { name: 'Agent pages', exact: true })
    await page.getByRole('button', { name: 'Show all conversations', exact: true }).click()
    const roomPages = page.getByRole('navigation', { name: 'Conversation pages', exact: true })
    await expect(page.getByRole('button', { name: /^New conversation with Agent / })).toHaveCount(50)
    await expect(page.locator('.room-item--card')).toHaveCount(50)
    if (count === 50) {
      await expect(agentPages).toHaveCount(0)
      await expect(roomPages).toHaveCount(0)
      return
    }
    await agentPages.getByRole('button', { name: '2', exact: true }).click()
    await expect(page.getByRole('button', { name: 'New conversation with Agent 51', exact: true })).toBeVisible()
    await expect(page.locator('.room-item--card').first()).toContainText('Conversation 1')
    await page.getByRole('button', { name: 'New conversation with Agent 51', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Conversation name', exact: true })).toHaveValue('Agent 51 (2)')
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await roomPages.getByRole('button', { name: String(Math.ceil(count / 50)), exact: true }).click()
    await expect(page.locator('.room-item--card').last()).toContainText(`Conversation ${count}`)
    expect(state.recipientRequests.every(request => request.page_size === '50')).toBe(true)
    expect(state.requests.every(request => request.page_size === '50')).toBe(true)
    await page.getByRole('textbox', { name: 'Search conversations…' }).fill(`Conversation ${count}`)
    await expect(page.locator('.room-item--card')).toHaveCount(1)
    await expect(roomPages).toHaveCount(0)
    await expect(agentPages).toBeVisible()
    await expect.poll(() => state.requests.at(-1)?.page).toBe('1')
    if (count === 1000) {
      await agentPages.getByRole('combobox').click()
      await page.getByRole('option', { name: '500', exact: true }).click()
      await expect(page.getByRole('button', { name: /^New conversation with Agent / })).toHaveCount(500)
      await expect.poll(() => state.recipientRequests.at(-1)).toEqual({ page: '1', page_size: '500' })
      await agentPages.getByRole('combobox').click()
      await page.getByRole('option', { name: '10', exact: true }).click()
      await expect(page.getByRole('button', { name: /^New conversation with Agent / })).toHaveCount(10)
      await page.setViewportSize({ width: 1440, height: 900 })
      await agentPages.getByRole('button', { name: '100', exact: true }).click()
      await expect(page.getByRole('button', { name: 'New conversation with Agent 1000', exact: true })).toBeVisible()
    }
  })
}

test('chat home can retry loading agents while recent conversations remain available', async ({ page }) => {
  await home(page, { failRecipients: true })
  await expect(page.getByRole('alert')).toContainText('Unable to load agents.')
  await expect(page.getByRole('button', { name: /Project outline Alice/ })).toBeVisible()
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(page.getByRole('button', { name: 'New conversation with Alice', exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('home shows recent activity by default and switches to the full history with the keyboard', async ({ page }) => {
  const state = await home(page, { rooms: [room,
    { ...room, id: 'old', label: 'Older exchange', last_message: { ...message, created_at: '2026-09-24T12:00:00Z' } },
    { ...room, id: 'empty', label: 'No messages yet', last_message: null },
  ] })
  await expect(page.getByRole('button', { name: /Project outline Alice/ })).toBeVisible()
  await expect(page.getByText('Older exchange', { exact: true })).toHaveCount(0)
  await expect(page.getByText('No messages yet', { exact: true })).toHaveCount(0)
  await expect.poll(() => state.requests.at(-1)?.recent_days).toBe('7')
  const all = page.getByRole('button', { name: 'Show all conversations', exact: true })
  await all.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('Older exchange', { exact: true })).toBeVisible()
  await expect(page.getByText('No messages yet', { exact: true })).toBeVisible()
  expect(state.requests.at(-1)).not.toHaveProperty('recent_days')
  await page.getByRole('button', { name: 'Show conversations from the last 7 days', exact: true }).click()
  await expect(page.getByText('Older exchange', { exact: true })).toHaveCount(0)
  await expect.poll(() => state.requests.at(-1)?.recent_days).toBe('7')
})

test('home can open the full history when there is no recent activity and ignore its late response', async ({ page }) => {
  await home(page, { rooms: [{ ...room, last_message: { ...message, created_at: '2026-09-24T12:00:00Z' } }] })
  await expect(page.getByText('No conversations to display.')).toBeVisible()
  let deferredRoute
  await page.route('**/api/chat/rooms?*', route => {
    if (new URL(route.request().url()).searchParams.has('recent_days')) return route.fallback()
    deferredRoute = route
  })
  await page.getByRole('button', { name: 'Show all conversations', exact: true }).click()
  await expect.poll(() => Boolean(deferredRoute)).toBe(true)
  await page.getByRole('button', { name: 'Show conversations from the last 7 days', exact: true }).click()
  await expect(page.getByText('No conversations to display.')).toBeVisible()
  await deferredRoute.fulfill({ json: { items: [room], total: 1, page: 1, page_size: 50 } })
  await expect(page.getByText('Project outline', { exact: true })).toHaveCount(0)
})

test('recent conversation pagination recovers from errors and ignores a late page after filtering', async ({ page }) => {
  const rooms = Array.from({ length: 51 }, (_, index) => ({ ...room, id: `room-${index + 1}`, label: `Conversation ${index + 1}` }))
  await home(page, { rooms })
  const pagination = page.getByRole('navigation', { name: 'Conversation pages', exact: true })
  let deferredRoute
  let fail = true
  await page.route('**/api/chat/rooms?*', route => {
    if (new URL(route.request().url()).searchParams.get('page') !== '2') return route.fallback()
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } })
    deferredRoute = route
  })
  await pagination.getByRole('button', { name: '2', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText('No conversations to display.')).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect.poll(() => Boolean(deferredRoute)).toBe(true)
  await page.getByRole('textbox', { name: 'Search conversations…' }).fill('missing')
  await expect(page.getByText('No conversations to display.')).toBeVisible()
  await deferredRoute.fulfill({ json: { items: rooms.slice(50), total: 51, page: 2, page_size: 50 } })
  await expect(pagination).toHaveCount(0)
  await expect(page.locator('.room-item--card')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
})
