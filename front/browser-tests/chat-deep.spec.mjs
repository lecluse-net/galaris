import { test, expect, jsonRoute, mount } from './fixtures.mjs'

for (const width of [1280, 390]) {
test(`Deep follows and restores the direct stream at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 844 })
  const room = { id: 'room-deep', label: 'Synthetic Deep conversation', kind: 'direct',
    agent_id: 7, agent_name: 'Alice', agent_active: false, source: null, writable: true,
    members: [], muted: false, archived: false, unread_count: 0, conversation_type: 'text' }
  const messages = []
  const streamReads = []
  const fragments = [
    { sequence: 1, kind: 'text', payload: { content: 'Synthetic ' } },
    { sequence: 2, kind: 'activity', payload: {
      activity_ref: 'agent:review', tool_name: 'Review', activity_state: 'running', content: 'Inspect sample checkout',
    } },
    { sequence: 3, kind: 'activity', payload: {
      activity_ref: 'command:test', parent_activity_ref: 'agent:review', tool_name: 'make tests', activity_state: 'completed',
      content: 'Synthetic tests passed',
    } },
    { sequence: 4, kind: 'text', payload: { content: 'response.' } },
  ]
  let enabled = false
  let submission = null
  for (const [url, value] of [
    ['**/api/chat/status', { enabled: true, chat_enabled: true, max_attachment_bytes: 1000000 }],
    ['**/api/chat/inbox', { unread_count: 0 }],
    ['**/api/chat/rooms?*', { items: [room], total: 1 }],
    ['**/api/chat/rooms/room-deep', room],
    ['**/api/chat/rooms/room-deep/activity?*', { items: [], total: 0 }],
    ['**/api/chat/rooms/room-deep/read', {}],
    ['**/api/chat/rooms/room-deep/commands', { commands: ['task', 'deep'] }],
    ['**/api/chat/rooms/room-deep/speech/status*', { available_agent_ids: [] }],
    ['**/api/chat/rooms/room-deep/messages/*/previews*', []],
    ['**/api/chat/emojis/frequent', { items: [] }],
  ]) await jsonRoute(page, url, value)
  await page.route('**/api/chat/agents/7/avatar', route => route.fulfill({
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="#16425b"/><text x="16" y="22" text-anchor="middle" fill="white" font-size="16">A</text></svg>',
  }))
  await page.route('**/api/chat/rooms/room-deep/deep', route =>
    route.fulfill({ json: { enabled, submissions: submission ? [submission] : [] } }))
  await page.route('**/api/chat/rooms/room-deep/deep/*/events?*', route => {
    const after = Number(new URL(route.request().url()).searchParams.get('after'))
    streamReads.push(after)
    return route.fulfill({ json: fragments.filter(event => event.sequence > after && event.sequence <= submission.sequence) })
  })
  await page.route('**/api/chat/rooms/room-deep/messages?*', route =>
    route.fulfill({ json: { items: messages, total: messages.length, page: 1 } }))
  await page.route('**/api/chat/rooms/room-deep/messages', route => {
    const body = route.request().postDataJSON()
    const message = { id: body.client_message_id, external_id: body.client_message_id, room_id: room.id,
      direction: 'inbound', text: body.text, created_at: new Date().toISOString(),
      sender: null, files: [], is_mine: true, status: 'admitted' }
    messages.push(message)
    const text = body.text.trim()
    if (text === '@deep') enabled = !enabled
    else {
      if (text.startsWith('@deep ')) enabled = true
      submission = { id: 'submission-one', session_id: 'session-one', message_id: message.id,
        response_message_id: null, state: 'running', sequence: 0, stop_requested: false, has_activity: false, approvals: [] }
    }
    return route.fulfill({ status: 201, json: message })
  })

  const open = async () => {
    await mount(page, 'app/chat/pages/index.vue', {
      route: '/chat?room=room-deep', browserHistory: true, privileges: ['CHAT_SEND'], shell: true, dark: width < 1024,
    })
    if (width < 1024) {
      const backdrop = page.locator('.q-drawer__backdrop')
      await expect(backdrop).toBeVisible()
      await backdrop.click({ position: { x: width - 15, y: 120 } })
      await expect(backdrop).toBeHidden()
    }
  }
  const socket = (name, data) => page.evaluate(({ name, data }) => window.testApp.emitSocket(name, { data }), { name, data })
  await open()
  const header = page.locator('.conversation-toolbar')
  await expect(header.getByText('Deep off', { exact: true })).toBeVisible()
  const composer = page.getByPlaceholder('Write a message…')
  const send = () => width >= 1024 ? composer.press('Enter') : page.getByRole('button', { name: 'Post', exact: true }).click()
  await page.getByRole('button', { name: 'Show @ commands' }).click()
  await page.getByText('@deep', { exact: true }).click()
  await expect(composer).toHaveValue('@deep')
  if (width >= 1024) {
    await send()
    await expect(header.getByText('Deep', { exact: true })).toBeVisible()
    await composer.fill('Run the synthetic checks')
  } else {
    await composer.press('End')
    await composer.press('Space')
    await composer.pressSequentially('Run the synthetic checks')
    await expect(composer).toHaveValue('@deep Run the synthetic checks')
  }
  await send()
  await expect(header.getByText('Deep', { exact: true })).toBeVisible()
  const reply = page.locator('.message-row').filter({ has: page.getByText('Details', { exact: true }) })
  const details = reply.getByRole('button', { name: 'Details', exact: true })
  await expect(reply.getByRole('button', { name: 'Stop this execution' })).toBeVisible()
  await expect(details).toHaveCount(0)
  submission.sequence = 1
  await socket('chat.deep', { room_id: room.id })
  await expect(reply.getByText('Synthetic', { exact: true })).toBeVisible()
  await expect(reply.getByRole('img', { name: 'Alice' })).toHaveJSProperty('naturalWidth', 32)
  await expect(reply.getByRole('button', { name: 'Stop this execution' })).toBeVisible()
  await expect(details).toHaveCount(0)
  await reply.screenshot({ path: testInfo.outputPath(`deep-stream-${width}.png`), animations: 'disabled' })

  submission.sequence = fragments.length
  submission.has_activity = true
  await socket('chat.deep', { room_id: room.id })
  await expect(reply.getByText('Synthetic response.', { exact: true })).toBeVisible()
  await expect(details).toHaveAttribute('aria-expanded', 'false')
  await details.click()
  await reply.getByText('Review', { exact: true }).last().click()
  await reply.getByText('make tests', { exact: true }).click()
  await expect(reply.getByText('Synthetic tests passed', { exact: true })).toBeVisible()

  await open()
  await expect(header.getByText('Deep', { exact: true })).toBeVisible()
  await expect(page.getByText('Synthetic response.', { exact: true })).toHaveCount(1)
  expect(streamReads.filter(after => after === 0).length).toBeGreaterThanOrEqual(2)

  // A Messenger response may be visible before the updated submission status.
  messages.push({ id: 'final-deep', external_id: 'final-deep', room_id: room.id,
    direction: 'outbound', text: 'Synthetic response.', created_at: new Date().toISOString(),
    sender: { display_name: 'Alice', agent_id: 7, is_ai: true }, deep_submission_id: submission.id,
    files: [], is_mine: false, status: 'accepted' })
  await socket('chat.message', { room_id: room.id, is_new: true })
  await expect(reply).toHaveAttribute('data-message-id', 'final-deep')
  await expect(page.getByText('Synthetic response.', { exact: true })).toHaveCount(1)
  submission.state = 'completed'
  submission.response_message_id = 'final-deep'
  await socket('chat.deep', { room_id: room.id })
  await expect(reply.getByRole('button', { name: 'Stop this execution' })).toHaveCount(0)

  const readsBeforeReopen = streamReads.length
  await open()
  await expect(details).toHaveAttribute('aria-expanded', 'false')
  expect(streamReads).toHaveLength(readsBeforeReopen)
  await details.click()
  await reply.getByText('Review', { exact: true }).last().click()
  await reply.getByText('make tests', { exact: true }).click()
  await expect(reply.getByText('Synthetic tests passed', { exact: true })).toBeVisible()

  await composer.fill('@deep')
  await send()
  await expect(header.getByText('Deep off', { exact: true })).toBeVisible()
  await open()
  await expect(header.getByText('Deep off', { exact: true })).toBeVisible()
})
}

test('Deep failures explain the cause without offering empty Details', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/rooms/room/speech/status*', { available_agent_ids: [] })
  await page.route('**/api/chat/agents/7/avatar', route => route.fulfill({ status: 404 }))
  const input = {
    id: 'input-1', external_id: 'input-1', room_id: 'room', direction: 'inbound',
    text: 'Synthetic request', created_at: '2026-11-20T11:00:00Z', is_mine: true, files: [],
  }
  const failure = {
    id: 'deep-failure', session_id: 'deep-session', message_id: input.id,
    response_message_id: null, state: 'failed', sequence: 1, stop_requested: false,
    has_activity: false, approvals: [], failure: { code: 'http', http_status: 422 },
  }
  const props = { roomId: 'room', agentId: 7, agentName: 'Alice', messages: [input], activity: [], liveRound: null }
  const open = () => mount(page, 'app/chat/components/MessageTimeline.vue', {
    locale: 'fr', props: { ...props, deepSubmissions: [failure] },
  })
  await open()
  const details = page.getByRole('button', { name: 'Détails', exact: true })
  const reason = page.getByText('Le harnais a reçu une erreur HTTP 422.', { exact: true })
  await expect(reason).toBeVisible()
  await expect(page.getByText('Détails', { exact: true })).toBeVisible()
  await expect(details).toHaveCount(0)
  await open()
  await expect(reason).toBeVisible()
})
