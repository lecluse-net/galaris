import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

async function workspace(page, privileges = ['DOCUMENT_EDIT', 'CHAT_ACCESS', 'CHAT_SEND', 'CHAT_MANAGE'], roomCount = 1, notificationSurface = null) {
  if (notificationSurface) await page.addInitScript(() => localStorage.setItem('access_token', 'synthetic-notification-session'))
  const id = '00000000-0000-4000-8000-000000000321'
  const state = { item: { ...documentFixture, id, owner_agent_id: null, owner_user_id: 1,
    media_type: 'text/html', content_profile: 'document', payload: { text: '<h1>Synthetic report</h1><p>Working content</p>' } },
    refuseSave: false, refuseSend: false, refuseRooms: 0, roomRequests: [], reads: [], writes: [], operations: [], created: [],
    preferences: new Map(), preferenceReads: [], preferenceWrites: [], refusePreferenceRead: false, refusePreferenceWrite: false }
  const room = { id: 'room-a', label: 'Existing conversation', agent_id: 7, agent_name: 'Synthetic agent',
    agent_active: false, source: null, writable: true, members: [], muted: false, archived: false, unread_count: 0, conversation_type: 'text' }
  const rooms = [room, ...Array.from({ length: roomCount - 1 }, (_, index) => ({
    ...room, id: `room-${index + 2}`, label: `Conversation ${String(index + 2).padStart(3, '0')}`,
  }))]
  const message = { id: 'message-a', room_id: room.id, text: 'Earlier exchange', files: [], sender: null,
    created_at: '2026-09-01T12:00:00Z', is_mine: true, status: 'sent' }
  const messages = [message]
  state.documents = new Map([[id, state.item]])
  state.receive = (roomId, id, text) => {
    const incoming = { ...message, id, room_id: roomId, text, is_mine: false,
      created_at: new Date(Date.parse(message.created_at) + messages.length * 1000).toISOString() }
    messages.push(incoming)
    Object.assign(rooms.find(room => room.id === roomId), { last_message: incoming, unread_count: 1, show_last_message: true })
  }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/agents/selection?scope=dialogue', [{ id: 7, label: 'Synthetic agent', has_avatar: false }])
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [] })
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, `**/api/documents/${id}/attachments*`, [])
  await page.route('**/api/documents/library', route => route.fulfill({ json: {
    entries: [...state.documents.values()].map(item => ({ item, tags: [], agent_ids: [], writable_agent_ids: [], user_access: item.access })), total: state.documents.size, has_more: false,
  } }))
  await page.route(/\/api\/documents\/([0-9a-f-]+)(?:\?.*)?$/, route => {
    const documentId = new URL(route.request().url()).pathname.split('/').at(-1)
    const item = documentId === id ? state.item : state.documents.get(documentId)
    if (!item) return route.fulfill({ status: 404, json: { detail: 'Missing document' } })
    if (route.request().method() === 'PATCH') {
      state.operations.push('save')
      if (state.refuseSave) return route.fulfill({ status: 503, json: { detail: 'Save unavailable' } })
      const updated = { ...item, ...route.request().postDataJSON(), revision: item.revision + 1 }
      state.documents.set(documentId, updated)
      if (documentId === id) state.item = updated
      return route.fulfill({ json: updated })
    }
    return route.fulfill({ json: { item, agent_id: null } })
  })
  await page.route('**/api/chat/documents/*/conversation', async route => {
    const documentId = new URL(route.request().url()).pathname.split('/').at(-2)
    if (route.request().method() === 'PUT') {
      if (state.refusePreferenceWrite) return route.fulfill({ status: 503, json: { detail: 'Save unavailable' } })
      const value = route.request().postDataJSON()
      state.preferences.set(documentId, value.room_id)
      state.preferenceWrites.push({ documentId, ...value })
      return route.fulfill({ json: value })
    }
    const roomId = state.preferences.get(documentId) ?? null
    state.preferenceReads.push(documentId)
    if (state.refusePreferenceRead) return route.fulfill({ status: 503, json: { detail: 'Read unavailable' } })
    if (state.waitPreferenceRead) await state.waitPreferenceRead(documentId)
    return route.fulfill({ json: { room_id: roomId } })
  })
  await jsonRoute(page, '**/api/chat/status', { enabled: true, chat_enabled: true, max_attachment_bytes: 1000000 })
  await jsonRoute(page, '**/api/chat/push/configuration', { available: false, public_key: '' })
  await jsonRoute(page, '**/api/mail/status', { enabled: false })
  await page.route('**/api/chat/inbox', route => route.fulfill({ json: { unread_count: rooms.reduce((total, room) => total + room.unread_count, 0) } }))
  await page.route('**/api/chat/rooms?*', async route => {
    if (state.waitRooms) await state.waitRooms()
    const query = new URL(route.request().url()).searchParams
    const currentPage = Number(query.get('page') ?? 1), size = Number(query.get('page_size') ?? 50)
    const search = query.get('search') ?? ''
    state.roomRequests.push({ page: currentPage, size, search })
    if (state.refuseRooms) return route.fulfill({ status: state.refuseRooms, json: { detail: 'List unavailable' } })
    const matches = rooms.filter(room => room.label.toLowerCase().includes(search.toLowerCase()))
    return route.fulfill({ json: { items: matches.slice((currentPage - 1) * size, currentPage * size), total: matches.length, page: currentPage, page_size: size } })
  })
  await page.route(/\/api\/chat\/rooms\/room-(?:[ab]|\d+)(?:\?.*)?$/, route => route.fulfill({ json: rooms.find(room => new URL(route.request().url()).pathname.endsWith(`/${room.id}`)) }))
  await jsonRoute(page, '**/api/chat/rooms/*/activity?*', { items: [], total: 0 })
  await jsonRoute(page, '**/api/chat/rooms/*/documents?*', { items: [], total: 0 })
  await jsonRoute(page, '**/api/documents/*/attachments*', [])
  await page.route('**/api/chat/rooms/*/messages?*', async route => {
    const roomId = route.request().url().match(/rooms\/([^/]+)/)[1]
    if (state.waitMessages) await state.waitMessages(roomId)
    const items = messages.filter(message => message.room_id === roomId || message.id === 'message-a')
    return route.fulfill({ json: { items, total: items.length } })
  })
  await jsonRoute(page, '**/api/chat/rooms/*/commands', { commands: [] })
  await page.route('**/api/chat/rooms/*/read', route => {
    const roomId = route.request().url().match(/rooms\/([^/]+)/)[1]
    state.reads.push({ roomId, ...route.request().postDataJSON() })
    rooms.find(room => room.id === roomId).unread_count = 0
    return route.fulfill({ json: {} })
  })
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  await jsonRoute(page, '**/api/chat/rooms/*/speech/status*', { available_agent_ids: [] })
  await page.route('**/api/chat/agents/7/avatar', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="#0466c8"/><circle cx="20" cy="20" r="10" fill="white"/></svg>' }))
  await jsonRoute(page, '**/api/chat/recipients?*', { agents: [{ agent_id: 7, display_name: 'Synthetic agent', active: true, suggested_room_label: 'New conversation' }] })
  await page.route('**/api/chat/rooms', route => {
    state.created.push(route.request().postDataJSON())
    const created = { ...room, id: 'room-b', label: state.created.at(-1).label }
    rooms.push(created)
    return route.fulfill({ json: created })
  })
  await page.route('**/api/chat/rooms/*/messages', route => {
    const body = route.request().postDataJSON()
    state.operations.push('message')
    if (state.refuseSend) return route.fulfill({ status: 503, json: { detail: 'Send unavailable' } })
    state.writes.push({ ...body, room: route.request().url().match(/rooms\/([^/]+)/)[1] })
    return route.fulfill({ json: { ...message, id: 'message-b', text: body.text, external_id: body.client_message_id } })
  })
  await mount(page, notificationSurface ? 'test-support/browser/ConversationNotificationsHarness.vue' : 'app/document/components/DocumentLibraryPage.vue', {
    route: notificationSurface === 'chat' ? '/chat?room=room-a' : `/documents?document_id=${id}`, privileges,
  })
  if (notificationSurface !== 'chat') await expect(page.getByLabel('Title', { exact: true })).toHaveValue(state.item.title)
  else await expect(page.locator('.conversation-pane')).toContainText('Earlier exchange')
  return state
}

async function openConversation(page) {
  const trigger = page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true })
  await trigger.click()
  const panel = page.getByRole('region', { name: 'Conversation', exact: true })
  await panel.getByRole('combobox', { name: 'Open a conversation', exact: true }).click()
  await page.getByRole('option').filter({ hasText: 'Existing conversation' }).click()
  await expect(panel).toContainText('Earlier exchange')
  return panel
}

for (const mobile of [false]) test(`Documents saves before conversing and can create another conversation (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: mobile ? 390 : 1600, height: 1000 })
  const state = await workspace(page)
  const title = page.getByLabel('Title', { exact: true })
  await title.fill('Edited report')
  if (!mobile) await page.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  const panel = await openConversation(page)
  await expect.poll(() => state.preferences.get(state.item.id)).toBe('room-a')
  await expect(page.locator('.editorial-fullscreen')).toHaveCount(0)
  await panel.locator('textarea').fill('Work on this report')
  await panel.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(1)
  expect(state.operations.indexOf('save')).toBeLessThan(state.operations.indexOf('message'))
  expect(state.writes[0]).toMatchObject({ displayed_document_id: state.item.id, room: 'room-a' })
  if (!mobile) {
    const separator = page.getByRole('separator', { name: 'Resize document and conversation', exact: true })
    const width = async () => (await panel.boundingBox()).width
    const initialWidth = await width()
    const initialRatio = await separator.getAttribute('aria-valuenow')
    const handle = await separator.boundingBox()
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
    await page.mouse.down()
    await page.mouse.move(handle.x + handle.width / 2 + 80, handle.y + handle.height / 2, { steps: 8 })
    await page.mouse.up()
    // Quasar first moves the DOM, then commits the model at the end of the gesture.
    await expect(separator).not.toHaveAttribute('aria-valuenow', initialRatio)
    await expect.poll(width).toBeLessThan(initialWidth)
    const draggedWidth = await width()
    await separator.focus()
    await separator.press('ArrowLeft')
    await expect.poll(width).toBeGreaterThan(draggedWidth)
    await expect(title).toHaveValue('Edited report')
    await expect(panel).toContainText('Work on this report')
    await expect.poll(async () => Math.abs((await panel.boundingBox()).height
      - (await page.locator('.documents-conversation-splitter').boundingBox()).height)).toBeLessThan(2)
  }
  await panel.getByRole('button', { name: 'New conversation with an agent', exact: true }).click()
  const create = page.getByRole('dialog').filter({ hasText: 'New conversation' })
  await create.getByRole('combobox').click()
  await page.getByRole('option').filter({ hasText: 'Synthetic agent' }).click()
  await create.getByRole('button', { name: 'Chat', exact: true }).click()
  await expect.poll(() => state.created.length).toBe(1)
  await expect(panel.getByText('New conversation', { exact: true })).toBeVisible()
  await expect.poll(() => state.preferences.get(state.item.id)).toBe('room-b')
  await panel.locator('textarea').fill('Continue here')
  await panel.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(2)
  expect(state.writes[1].room).toBe('room-b')
  await page.screenshot({ path: testInfo.outputPath('document-conversation.png'), animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('document-conversation-dark.png'), animations: 'disabled' })
  await panel.locator('textarea').fill('Draft retained when hidden')
  await panel.getByRole('button', { name: 'Hide conversation', exact: true }).click()
  await expect(panel).toBeHidden()
  const trigger = page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true })
  await trigger.click()
  await expect(panel.locator('textarea')).toHaveValue('Draft retained when hidden')
  await expect(panel.getByText('New conversation', { exact: true })).toBeVisible()
  await panel.getByRole('button', { name: 'Hide conversation', exact: true }).click()
  await expect(panel).toBeHidden()
  await expect(title).toHaveValue('Edited report')
})

test('Documents loads the last conversation per document only after a manual opening', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 })
  const state = await workspace(page, undefined, 102)
  await expect(page.getByRole('region', { name: 'Conversation', exact: true })).not.toBeVisible()
  expect(state.preferenceReads).toEqual([])
  expect(state.roomRequests).toEqual([])
  const firstId = state.item.id
  const secondId = '00000000-0000-4000-8000-000000000322'
  state.documents.set(secondId, { ...state.item, id: secondId, title: 'Second synthetic document' })
  // Restoration is independent of the first picker page.
  state.preferences.set(firstId, 'room-102')
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Conversation', exact: true })
  await expect(panel).toContainText('Conversation 102')
  expect(state.preferenceWrites).toEqual([])
  await page.evaluate(id => window.testApp.navigate(`/documents?document_id=${id}`), secondId)
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Second synthetic document')
  await expect(panel).not.toBeVisible()
  expect(state.preferenceReads).toEqual([firstId])
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  await expect(panel).toContainText('Choose a conversation or start one with an agent.')
  expect(state.created).toEqual([])
  await expect(panel).not.toContainText('Conversation 102')
  await panel.getByRole('combobox', { name: 'Open a conversation', exact: true }).click()
  await page.getByRole('option').filter({ hasText: 'Existing conversation' }).click()
  await expect.poll(() => state.preferences.get(secondId)).toBe('room-a')
  await page.evaluate(id => window.testApp.navigate(`/documents?document_id=${id}`), firstId)
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(state.item.title)
  await expect(panel).not.toBeVisible()
  expect(state.preferenceReads).toEqual([firstId, secondId])
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  await expect(panel).toContainText('Conversation 102')
  // A new page instance reads server persistence, rather than its old in-memory selection.
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', {
    route: `/documents?document_id=${secondId}`, privileges: ['DOCUMENT_EDIT', 'CHAT_ACCESS', 'CHAT_SEND', 'CHAT_MANAGE'],
  })
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Second synthetic document')
  await expect(panel).not.toBeVisible()
  expect(state.preferenceReads).toEqual([firstId, secondId, firstId])
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  await expect(panel).toContainText('Existing conversation')
})

test('a late saved conversation does not reopen a panel the user just closed', async ({ page }) => {
  const state = await workspace(page)
  state.preferences.set(state.item.id, 'room-a')
  let release, entered
  const started = new Promise(resolve => { entered = resolve })
  const delayed = new Promise(resolve => { release = resolve })
  state.waitPreferenceRead = async () => { entered(); await delayed }
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', {
    route: `/documents?document_id=${state.item.id}`, privileges: ['DOCUMENT_EDIT', 'CHAT_ACCESS', 'CHAT_SEND', 'CHAT_MANAGE'],
  })
  const trigger = page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true })
  await trigger.click()
  await started
  await expect(trigger).toHaveAttribute('aria-expanded', 'true')
  await trigger.click()
  const response = page.waitForResponse(url => url.url().includes(`/chat/documents/${state.item.id}/conversation`))
  release()
  await response
  await expect(trigger).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('region', { name: 'Conversation', exact: true })).not.toBeVisible()
})

test('late preference responses cannot replace the conversation for the current document', async ({ page }) => {
  const state = await workspace(page, undefined, 2)
  const firstId = state.item.id
  const secondId = '00000000-0000-4000-8000-000000000322'
  state.documents.set(secondId, { ...state.item, id: secondId, title: 'Second synthetic document' })
  state.preferences.set(firstId, 'room-a')
  state.preferences.set(secondId, 'room-2')
  let release, entered
  const started = new Promise(resolve => { entered = resolve })
  const delayed = new Promise(resolve => { release = resolve })
  state.waitPreferenceRead = async id => { if (id === firstId) { entered(); await delayed } }
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  await started
  await page.evaluate(id => window.testApp.navigate(`/documents?document_id=${id}`), secondId)
  const panel = page.getByRole('region', { name: 'Conversation', exact: true })
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Second synthetic document')
  await expect(panel).not.toBeVisible()
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  await expect(panel).toContainText('Conversation 002')
  const response = page.waitForResponse(url => url.url().includes(`/chat/documents/${firstId}/conversation`))
  release()
  await response
  await expect(panel).toContainText('Conversation 002')
  expect(state.preferenceWrites).toEqual([])
})

test('preference failures are retryable and keep the selected conversation usable', async ({ page }) => {
  const state = await workspace(page)
  state.refusePreferenceRead = true
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Conversation', exact: true })
  await expect(panel.getByRole('alert')).toBeVisible()
  state.refusePreferenceRead = false
  await panel.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(panel.getByRole('alert')).toHaveCount(0)
  state.refusePreferenceWrite = true
  await panel.getByRole('combobox', { name: 'Open a conversation', exact: true }).click()
  await page.getByRole('option').filter({ hasText: 'Existing conversation' }).click()
  await expect(panel).toContainText('Earlier exchange')
  await expect(panel.getByRole('alert')).toBeVisible()
  await panel.locator('textarea').fill('Preserved draft')
  state.refusePreferenceWrite = false
  await panel.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(() => state.preferences.get(state.item.id)).toBe('room-a')
  await expect(panel.locator('textarea')).toHaveValue('Preserved draft')
})

test('opening a conversation saves the preference even while its history is loading', async ({ page }) => {
  const state = await workspace(page)
  let release
  const delayed = new Promise(resolve => { release = resolve })
  state.waitMessages = () => delayed
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Conversation', exact: true })
  await panel.getByRole('combobox', { name: 'Open a conversation', exact: true }).click()
  await page.getByRole('option').filter({ hasText: 'Existing conversation' }).click()
  await panel.getByRole('button', { name: 'Hide conversation', exact: true }).click()
  await expect.poll(() => state.preferences.get(state.item.id)).toBe('room-a')
  release()
})

test('a manual selection supersedes a pending saved conversation', async ({ page }) => {
  const state = await workspace(page, undefined, 2)
  state.preferences.set(state.item.id, 'room-a')
  let release, entered
  const started = new Promise(resolve => { entered = resolve })
  const delayed = new Promise(resolve => { release = resolve })
  state.waitPreferenceRead = async () => { entered(); await delayed }
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  await started
  const panel = page.getByRole('region', { name: 'Conversation', exact: true })
  await panel.getByRole('combobox', { name: 'Open a conversation', exact: true }).click()
  await page.getByRole('option').filter({ hasText: 'Conversation 002' }).click()
  await expect.poll(() => state.preferences.get(state.item.id)).toBe('room-2')
  const response = page.waitForResponse(url => url.url().includes(`/chat/documents/${state.item.id}/conversation`) && url.request().method() === 'GET')
  release()
  await response
  await expect(panel).toContainText('Conversation 002')
})

test('creating a conversation saves it before refreshing a slow room list', async ({ page }) => {
  const state = await workspace(page, undefined, 2)
  const panel = await openConversation(page)
  let release, delayed = false
  const waiting = new Promise(resolve => { release = resolve })
  state.waitRooms = async () => { if (!delayed && state.created.length) { delayed = true; await waiting } }
  await panel.getByRole('button', { name: 'New conversation with an agent', exact: true }).click()
  const create = page.getByRole('dialog').filter({ hasText: 'New conversation' })
  await create.getByRole('combobox').click()
  await page.getByRole('option').filter({ hasText: 'Synthetic agent' }).click()
  await create.getByRole('button', { name: 'Chat', exact: true }).click()
  await expect(panel.getByText('New conversation', { exact: true })).toBeVisible()
  await expect.poll(() => state.preferences.get(state.item.id)).toBe('room-b')
  await panel.getByRole('combobox', { name: 'Open a conversation', exact: true }).click()
  await page.getByRole('option').filter({ hasText: 'Conversation 002' }).click()
  await expect.poll(() => state.preferences.get(state.item.id)).toBe('room-2')
  const response = page.waitForResponse(url => url.url().includes('/chat/rooms?') && url.request().method() === 'GET')
  release()
  await response
  await expect(panel).toContainText('Conversation 002')
  expect(state.preferences.get(state.item.id)).toBe('room-2')
})

for (const surface of ['documents', 'chat']) for (const mobile of surface === 'chat' ? [false, true] : [false]) test(`visible conversations suppress notifications (${surface}, ${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
  await page.setViewportSize({ width: mobile ? 390 : 1600, height: 1000 })
  const state = await workspace(page, undefined, 2, surface)
  const panel = surface === 'documents' ? await openConversation(page) : page.locator('.conversation-pane')
  const displayed = () => page.evaluate(async () => {
    const { useChatInboxStore } = await import('/app/chat/stores/inbox.ts')
    return useChatInboxStore(window.testApp.pinia).displayedRoomId
  })
  await expect.poll(displayed).toBe('room-a')
  await page.clock.install()
  async function receive(roomId, messageId, text) {
    state.receive(roomId, messageId, text)
    await page.evaluate(data => window.testApp.emitSocket('chat.message', { data }), { room_id: roomId, message_id: messageId, is_new: true })
    await page.clock.runFor(4000)
  }
  await receive('room-a', 'visible-message', 'Message already on screen')
  await expect(panel).toContainText('Message already on screen')
  await expect.poll(() => state.reads.some(read => read.message_id === 'visible-message')).toBe(true)
  await expect(page.locator('.q-notification')).toHaveCount(0)
  async function setPageVisible(visible) {
    await page.evaluate(visible => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visible ? 'visible' : 'hidden' })
      document.dispatchEvent(new Event('visibilitychange'))
    }, visible)
  }
  await setPageVisible(false)
  await expect.poll(displayed).toBeNull()
  await receive('room-a', 'background-message', 'Message received in a hidden tab')
  const backgroundToast = page.locator('.q-notification').filter({ hasText: 'Message received in a hidden tab' })
  await expect(backgroundToast).toBeVisible()
  expect(state.reads.some(read => read.message_id === 'background-message')).toBe(false)
  await setPageVisible(true)
  await expect.poll(displayed).toBe('room-a')
  await expect(backgroundToast).toHaveCount(0)
  await expect.poll(() => state.reads.some(read => read.message_id === 'background-message')).toBe(true)
  await receive('room-2', 'other-message', 'Message from another conversation')
  const toast = page.locator('.q-notification').filter({ hasText: 'Message from another conversation' })
  await expect(toast).toBeVisible()
  if (surface === 'documents') {
    const chooser = panel.getByRole('combobox', { name: 'Open a conversation', exact: true })
    await chooser.click()
    await page.clock.runFor(500)
    await expect(page.getByRole('option').filter({ hasText: 'Conversation 002' })).toBeVisible()
    await chooser.press('ArrowDown')
    await chooser.press('Enter')
  } else {
    if (mobile) await page.getByRole('button', { name: 'Details', exact: true }).click()
    await page.locator('.room-item').filter({ hasText: 'Conversation 002' }).click()
  }
  await expect.poll(displayed).toBe('room-2')
  await expect(toast).toHaveCount(0)
  await expect(panel).toContainText('Message from another conversation')
  await receive('room-2', 'second-visible-message', 'New message in the displayed conversation')
  await expect(page.locator('.q-notification')).toHaveCount(0)
  await expect.poll(() => state.reads.some(read => read.message_id === 'second-visible-message')).toBe(true)
  if (surface === 'documents') {
    await panel.getByRole('button', { name: 'Hide conversation', exact: true }).click()
    await expect.poll(displayed).toBeNull()
    await receive('room-2', 'hidden-message', 'Message in a hidden conversation')
    const hiddenToast = page.locator('.q-notification').filter({ hasText: 'Message in a hidden conversation' })
    await expect(hiddenToast).toBeVisible()
    expect(state.reads.some(read => read.message_id === 'hidden-message')).toBe(false)
    await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
    await expect.poll(displayed).toBe('room-2')
    await expect(hiddenToast).toHaveCount(0)
    await expect.poll(() => state.reads.some(read => read.message_id === 'hidden-message')).toBe(true)
  }
  await receive('room-a', 'return-message', 'Return to the first conversation')
  await page.locator('.q-notification').filter({ hasText: 'Return to the first conversation' }).getByRole('button', { name: 'Open', exact: true }).click()
  await expect.poll(displayed).toBe('room-a')
  await expect(page.locator('.conversation-pane')).toContainText('Return to the first conversation')
})

test('save and send failures retain the message, and hiding the panel preserves its draft', async ({ page }) => {
  const state = await workspace(page)
  const panel = await openConversation(page)
  const title = page.getByLabel('Title', { exact: true })
  state.refuseSave = true
  await title.fill('Keep unsaved title')
  await panel.locator('textarea').fill('Keep unsent message')
  await panel.getByRole('button', { name: 'Post', exact: true }).click()
  await expect(page.getByText('Automatic save failed', { exact: true }).first()).toBeVisible()
  expect(state.writes).toEqual([])
  await expect(panel.locator('textarea')).toHaveValue('Keep unsent message')
  state.refuseSave = false
  state.refuseSend = true
  await panel.getByRole('button', { name: 'Post', exact: true }).click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await expect(panel.locator('textarea')).toHaveValue('Keep unsent message')
  await panel.getByRole('button', { name: 'Hide conversation', exact: true }).click()
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  await expect(panel.locator('textarea')).toHaveValue('Keep unsent message')
  state.refuseSend = false
  await panel.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(1)
})

test('Documents exposes chat only with chat access, and read-only chat cannot send or create', async ({ page }) => {
  await workspace(page, ['DOCUMENT_EDIT'])
  await expect(page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true })).toHaveCount(0)
  await page.evaluate(() => window.testApp.unmount())
  await workspace(page, ['DOCUMENT_EDIT', 'CHAT_ACCESS'])
  const panel = await openConversation(page)
  await expect(panel.getByRole('button', { name: 'New conversation with an agent', exact: true })).toHaveCount(0)
  await expect(panel.getByRole('button', { name: 'Post', exact: true })).toHaveCount(0)
  await expect(panel.getByText('Read-only', { exact: true })).toBeVisible()
})

for (const mobile of [false]) test(`conversation picker paginates and searches without losing the active draft (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: mobile ? 390 : 1600, height: 1000 })
  const state = await workspace(page, undefined, 121)
  const panel = await openConversation(page)
  const chooser = panel.getByRole('combobox', { name: 'Open a conversation', exact: true })
  await panel.locator('textarea').fill('Draft across pages')
  await chooser.click()
  const pages = page.getByRole('navigation', { name: 'Conversation pages' })
  await expect(pages).toBeVisible()
  await pages.getByRole('button', { name: '3', exact: true }).click()
  await expect.poll(() => state.roomRequests.at(-1)).toMatchObject({ page: 3, size: 50 })
  await expect(page.getByRole('option').filter({ hasText: 'Conversation 101' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('conversation-picker.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(panel.locator('textarea')).toHaveValue('Draft across pages')
  await expect(panel.getByText('Existing conversation', { exact: true })).toBeVisible()

  await chooser.click()
  await pages.getByRole('combobox', { name: 'Per page', exact: true }).click()
  await page.getByRole('option', { name: '100', exact: true }).click()
  await expect.poll(() => state.roomRequests.at(-1)).toMatchObject({ page: 1, size: 100 })
  state.refuseRooms = 503
  await pages.getByRole('button', { name: '2', exact: true }).click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await page.keyboard.press('Escape')
  state.refuseRooms = 0
  await panel.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(panel.getByRole('alert')).toHaveCount(0)
  await expect.poll(() => state.roomRequests.at(-1)).toMatchObject({ page: 2, size: 100 })

  await chooser.fill('Conversation 12')
  await expect.poll(() => state.roomRequests.at(-1)).toEqual({ page: 1, size: 100, search: 'Conversation 12' })
  await expect(page.getByRole('option').filter({ hasText: 'Conversation 121' })).toBeVisible()
  await page.getByRole('option').filter({ hasText: 'Conversation 121' }).click()
  await expect(panel.getByText('Conversation 121', { exact: true })).toBeVisible()
  await expect(panel).toContainText('Earlier exchange')
  state.refuseRooms = 403
  await chooser.click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await expect(panel.getByText('Earlier exchange', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('option')).toHaveCount(0)
})

for (const mobile of [false]) for (const input of ['mouse', 'keyboard']) test(`document selection survives opening chat (${input}, ${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
  await page.setViewportSize({ width: mobile ? 390 : 1600, height: 1000 })
  const state = await workspace(page)
  const panel = await openConversation(page)
  await panel.getByRole('button', { name: 'Hide conversation', exact: true }).click()
  await page.getByLabel('Title', { exact: true }).fill('Selection report')
  const paragraph = page.locator('[data-editor-surface] p')
  await paragraph.scrollIntoViewIfNeeded()
  await paragraph.click()
  if (input === 'keyboard') {
    await page.keyboard.press('End')
    await page.keyboard.press('Shift+Home')
    // Tab must save the range before the next field takes focus.
    await page.keyboard.press('Tab')
  } else {
    const box = await paragraph.evaluate(element => {
      const range = document.createRange()
      range.selectNodeContents(element)
      const { x, y, width, height } = range.getBoundingClientRect()
      return { x, y, width, height }
    })
    await page.mouse.move(box.x + 1, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width - 1, box.y + box.height / 2, { steps: 8 })
    await page.mouse.up()
    await expect.poll(() => page.evaluate(() => window.getSelection().toString())).toBe('Working content')
  }
  await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  const draft = panel.locator('textarea')
  await draft.fill('Improve the selected passage')
  await expect(draft).toBeFocused()
  state.refuseSend = true
  await panel.getByRole('button', { name: 'Post', exact: true }).click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await expect(draft).toHaveValue('Improve the selected passage')
  state.refuseSend = false
  await panel.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(1)
  expect(state.writes[0]).toMatchObject({ displayed_document_id: state.item.id, document_focus: {
    revision: state.item.revision, surface: 'rendered',
    selection: { start: 16, end: 31, text: 'Working content', truncated: false },
    cursor: { offset: input === 'keyboard' ? 16 : 31 },
  } })
  // A deliberate caret move replaces the old range, even after returning from the chat.
  if (mobile) await panel.getByRole('button', { name: 'Hide conversation', exact: true }).click()
  await paragraph.click()
  await page.keyboard.press('Home')
  if (mobile) await page.getByRole('toolbar', { name: 'Content', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click()
  await draft.fill('Insert at the cursor')
  await panel.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(2)
  expect(state.writes[1].document_focus.selection).toBeNull()
  expect(state.writes[1].document_focus.cursor.offset).toBe(16)
  state.item = { ...state.item, revision: state.item.revision + 1, payload: { text: '<p>Replacement from a collaborator</p>' } }
  await page.evaluate(data => window.testApp.emitSocket('document.update', { data }), { id: state.item.id, node_kind: 'document', revision: state.item.revision })
  await expect(paragraph).toHaveText('Replacement from a collaborator')
  await draft.fill('Review the new version')
  await panel.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(3)
  expect(state.writes[2].document_focus).toMatchObject({ selection: null, cursor: null, revision: state.item.revision })
})
