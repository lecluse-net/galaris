import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

async function workspace(page, editable = true) {
  const room = { id: 'room-a', label: 'Document conversation', agent_id: 7, agent_name: 'Alice', agent_active: false, source: null, writable: true, members: [], muted: false, archived: false, unread_count: 0, conversation_type: 'text' }
  const message = { id: 'message-a', room_id: room.id, text: 'Conversation remains available', files: [], sender: null, created_at: '2026-09-01T12:00:00Z', is_mine: true, status: 'sent' }
  let document = { ...documentFixture, media_type: 'text/html', content_profile: 'document', payload: { text: '<p>Initial document body</p>' } }
  let denied = false
  let openedDocumentId = 'doc-a'
  const writes = []
  const documentWrites = []
  const operations = []
  await jsonRoute(page, '**/api/chat/status', { enabled: true, chat_enabled: true, max_attachment_bytes: 1000000 })
  await jsonRoute(page, '**/api/chat/rooms?*', { items: [room], total: 1 })
  await jsonRoute(page, '**/api/chat/rooms/room-a', room)
  await jsonRoute(page, '**/api/chat/rooms/room-a/activity?*', { items: [], total: 0 })
  await jsonRoute(page, '**/api/chat/rooms/room-a/messages?*', { items: [message], total: 1 })
  await page.route('**/api/chat/rooms/room-a/messages', route => {
    writes.push(route.request().postDataJSON())
    operations.push('message')
    return route.fulfill({ json: { ...message, id: 'message-b', text: writes.at(-1).text } })
  })
  await jsonRoute(page, '**/api/chat/rooms/room-a/read', {})
  await jsonRoute(page, '**/api/chat/inbox', { unread_count: 0 })
  await jsonRoute(page, '**/api/chat/rooms/room-a/commands', { commands: [] })
  await jsonRoute(page, '**/api/chat/rooms/room-a/speech/status*', { available_agent_ids: [] })
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  await jsonRoute(page, '**/api/chat/agents/7/avatar', {})
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords*', [])
  await jsonRoute(page, '**/api/memory/documents/folders*', [])
  await jsonRoute(page, '**/api/memory/documents/*/attachments*', [])
  const readDocument = route => denied ? route.fulfill({ status: 403, json: { detail: 'Forbidden' } }) : route.fulfill({ json: route.request().url().includes('/items/') ? document : { item: document, agent_id: 7 } })
  await page.route('**/api/memory/items/doc-a?*', readDocument)
  await page.route('**/api/memory/documents/doc-a', readDocument)
  await page.route('**/api/memory/documents/doc-b', route => {
    openedDocumentId = 'doc-b'
    if (route.request().method() === 'PATCH') {
      const change = route.request().postDataJSON()
      documentWrites.push(change)
      operations.push('save')
      document = { ...document, ...change, revision: document.revision + 1, lock_version: document.lock_version + 1 }
      return route.fulfill({ json: { ...document, id: 'doc-b', title: 'Off-list document' } })
    }
    return denied ? route.fulfill({ status: 403, json: { detail: 'Forbidden' } }) : route.fulfill({ json: { item: { ...document, id: 'doc-b', title: 'Off-list document' }, agent_id: null } })
  })
  await page.route('**/api/memory/documents/library', route => route.fulfill({ json: { entries: [{ item: { ...document, id: 'doc-b', title: 'Off-list document' }, agent_ids: [] }], total: 1, has_more: false } }))
  await jsonRoute(page, '**/api/chat/rooms/room-a/documents?*', { items: [{ id: document.id, label: document.title, uri: 'document://doc-a', revision: 3 }], total: 1 })
  await page.route('**/api/chat/rooms/room-a/documents', route => route.fulfill({ json: { id: document.id, label: route.request().postDataJSON().title, uri: 'document://doc-a' } }))
  await mount(page, 'app/chat/pages/index.vue', { route: '/chat?room=room-a', privileges: ['CHAT_SEND', 'MEMORY_ACCESS', ...(editable ? ['MEMORY_EDIT'] : [])] })
  await expect(page.locator('.conversation-pane')).toContainText(message.text)
  return {
    message,
    writes,
    documentWrites,
    operations,
    deny(value) { denied = value },
    async update(text, id = openedDocumentId) {
      document = { ...document, revision: document.revision + 1, payload: { text: `<p>${text}</p>` } }
      await page.evaluate(data => window.testApp.emitSocket('memory.update', { data }), { id, node_kind: 'document', revision: document.revision })
    },
  }
}

async function openFromSearch(page) {
  await page.getByRole('button', { name: 'Search accessible documents', exact: true }).click()
  await page.getByLabel('Open document Off-list document', { exact: true }).click()
  await expect(page.locator('.chat-document-pane')).toContainText('document body')
}

test('document dialogs cover the split editor toolbar and keep their own formatting usable', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await workspace(page)
  await page.route('**/api/memory/documents/doc-a', route => route.request().method() === 'PATCH'
    ? route.fulfill({ json: { ...documentFixture, ...route.request().postDataJSON(), revision: 4, lock_version: 4 } })
    : route.fallback())
  await jsonRoute(page, '**/api/memory/documents/doc-b', { item: {
    ...documentFixture, id: 'doc-b', title: 'Off-list document', media_type: 'text/html', content_profile: 'document',
    payload: { text: '<p>Initial document body</p>'.repeat(60) },
  }, agent_id: null })
  await openFromSearch(page)
  await page.getByText('Working documents', { exact: true }).first().click()
  const background = page.locator('.chat-document-pane')
  const toolbar = background.getByRole('toolbar', { name: 'Editor toolbar', exact: true })
  const dialog = page.getByRole('dialog')
  await background.locator('.chat-document-content').evaluate(element => { element.scrollTop = 650 })
  await expect(toolbar).toBeInViewport()
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await page.getByRole('button', { name: 'Open document Test document in a dialog', exact: true }).click()
    await expect(dialog.locator('.ck-editor__editable')).toBeVisible()
    // Hit testing proves that the dialog or its backdrop covers the background toolbar.
    await expect.poll(() => toolbar.evaluate(element => {
      const box = element.getBoundingClientRect()
      const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
      return Boolean(hit?.closest('.q-dialog'))
    })).toBe(true)
    const editor = dialog.locator('.ck-editor__editable')
    await editor.click()
    await dialog.getByRole('button', { name: /, Heading$/ }).click()
    await dialog.getByRole('menuitemradio', { name: 'Heading 2', exact: true }).click()
    await expect(editor.locator('h2')).toContainText('Initial document body')
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(dialog).toHaveCount(0)
    await expect(background.locator('.ck-editor__editable')).toContainText('Initial document body')
    await toolbar.getByRole('button', { name: 'Bold', exact: true }).click()
  }
})

for (const width of [1440, 390]) {
  test(`document_show opens and reopens the current room's document at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await workspace(page)
    const draft = page.locator('.conversation-pane textarea')
    await draft.fill('Keep my message')
    const show = roomId => page.evaluate(room_id => window.testApp.emitSocket('chat.document_show', {
      data: { room_id, document_id: 'doc-a' },
    }), roomId)
    await show('other-room')
    await expect(page.locator('.chat-document-pane')).toHaveCount(0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await show('room-a')
      const viewer = width < 1024 ? page.getByRole('dialog') : page.locator('.chat-document-pane')
      await expect(viewer).toContainText('Initial document body')
      await viewer.getByRole('button', { name: width < 1024 ? 'Close' : 'Close working document', exact: true }).click()
      await expect(viewer).toHaveCount(0)
    }
    await expect(draft).toHaveValue('Keep my message')
  })
}

test('document_show saves an existing draft before opening another document', async ({ page }) => {
  const state = await workspace(page)
  await openFromSearch(page)
  await page.locator('.chat-document-pane .ck-editor__editable').fill('Preserve this edit')
  await page.evaluate(() => window.testApp.emitSocket('chat.document_show', {
    data: { room_id: 'room-a', document_id: 'doc-a' },
  }))
  await expect.poll(() => state.documentWrites.length).toBeGreaterThan(0)
  expect(state.documentWrites.at(-1).payload.text).toContain('Preserve this edit')
  await expect(page.locator('.chat-document-pane')).toContainText('Test document')
})

test('document_show cannot switch rooms while waiting for a document save', async ({ page }) => {
  await workspace(page)
  await openFromSearch(page)
  let release
  await page.route('**/api/memory/documents/doc-b', async route => {
    if (route.request().method() !== 'PATCH') return route.fallback()
    await new Promise(resolve => { release = resolve })
    return route.fulfill({ json: { ...documentFixture, id: 'doc-b', title: 'Off-list document',
      ...route.request().postDataJSON(), revision: 4, lock_version: 4 } })
  })
  await page.locator('.chat-document-pane .ck-editor__editable').fill('Save before switching')
  await page.evaluate(() => window.testApp.emitSocket('chat.document_show', {
    data: { room_id: 'room-a', document_id: 'doc-a' },
  }))
  await expect.poll(() => Boolean(release)).toBeTruthy()
  await page.evaluate(() => window.testApp.patchStore('app/chat/stores/chat.ts', 'useChatStore', {
    selectedRoom: null,
  }))
  release()
  await expect(page.locator('.chat-document-pane')).toHaveCount(0)
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('document_show respects denied access and leaves the chat usable', async ({ page }) => {
  const state = await workspace(page, false)
  state.deny(true)
  await page.evaluate(() => window.testApp.emitSocket('chat.document_show', {
    data: { room_id: 'room-a', document_id: 'doc-a' },
  }))
  await expect(page.locator('.chat-document-pane').getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  await expect(page.locator('.chat-document-pane')).not.toContainText('Initial document body')
  await expect(page.locator('.conversation-pane textarea')).toBeEditable()
})

for (const [width, editable, mode] of [[1440, true, undefined], [1440, true, 'split'], [1440, true, 'dialog'], [390, true, 'split'], [390, true, 'dialog'], [1440, false, 'split']]) {
  test(`document previews respect the ${mode ?? 'default'} preference at ${width}px (editable: ${editable})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const state = await workspace(page, editable)
    await page.evaluate(mode => window.testApp.auth.$patch({ user: { document_open_mode: mode } }), mode)
    const id = '00000000-0000-0000-0000-000000000001'
    await jsonRoute(page, '**/api/memory/documents/icons/resolve', { [id]: 'emoji:1F680' })
    await jsonRoute(page, '**/api/memory/documents/tag-icons', [])
    const uri = `document://${id}`
    state.message.text = uri
    let document = { ...documentFixture, id, title: 'Preview document', media_type: 'text/html', content_profile: 'document', payload: { text: '<p>Document from the message</p>' } }
    await jsonRoute(page, '**/api/chat/rooms/room-a/messages/message-a/previews*', [{
      uri, kind: 'document', title: document.title, description: 'Document from the message', subtitle: '',
      media_type: 'text/html', image_available: false, download_available: false, open_mode: 'internal', metadata: {},
    }])
    const documentRoute = route => {
      if (['PATCH', 'PUT'].includes(route.request().method())) {
        document = { ...document, ...route.request().postDataJSON(), revision: document.revision + 1, lock_version: document.lock_version + 1 }
        state.operations.push('save')
        return route.fulfill({ json: document })
      }
      return route.fulfill({ json: route.request().url().includes('/items/') ? document : { item: document, agent_id: 7 } })
    }
    await page.route(`**/api/memory/documents/${id}`, documentRoute)
    await page.route(`**/api/memory/items/${id}*`, documentRoute)
    await page.evaluate(({ uri, message }) => window.testApp.patchStore(
      'app/chat/stores/chat.ts', 'useChatStore', { messages: [{ ...message, text: uri }] },
    ), { uri, message: state.message })
    const card = page.locator('.resource-preview-card').filter({ hasText: 'Preview document' })
    const documentIcon = card.getByRole('button', { name: 'Icon for document Preview document', exact: true })
    await expect(documentIcon).toContainText('🚀')
    await documentIcon.click()
    await expect(page.getByLabel('Search icons', { exact: true })).toBeVisible()
    await expect(page.locator('.chat-document-pane')).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(page.getByLabel('Search icons', { exact: true })).toHaveCount(0)
    await expect(card).toBeVisible()
    const action = card.getByRole('button', { name: 'Open in co-editing', exact: true })
    if (!editable || width < 1024) {
      await expect(action).toHaveCount(0)
      await card.locator('.resource-preview-main').click()
      await expect(page.getByRole('dialog')).toContainText('Document from the message')
      await expect(page.locator('.chat-document-pane')).toHaveCount(0)
      await expect(page.getByRole('separator', { name: 'Resize chat and document', exact: true })).toHaveCount(0)
      return
    }
    const draft = page.locator('.conversation-pane textarea')
    await draft.fill('Review our document')
    await card.locator('.resource-preview-main').click()
    if (mode === 'dialog') {
      await expect(page.getByRole('dialog')).toContainText('Document from the message')
      await expect(page.locator('.chat-document-pane')).toHaveCount(0)
      await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
      await action.press('Enter')
    }
    const pane = page.locator('.chat-document-pane')
    await expect(pane).toContainText('Document from the message')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await card.hover()
    await card.locator('.resource-preview-actions').getByRole('button', { name: 'Show preview of Preview document', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('Document from the message')
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    await expect(draft).toHaveValue('Review our document')
    const editor = pane.locator('.ck-editor__editable')
    await expect(editor).toBeEditable()
    await editor.fill('Edited from its preview')
    await page.getByRole('button', { name: 'Post', exact: true }).click()
    await expect.poll(() => state.writes.length).toBe(1)
    expect(document.payload.text).toContain('Edited from its preview')
    expect(state.operations.indexOf('save')).toBeLessThan(state.operations.indexOf('message'))
    expect(state.writes[0]).toMatchObject({ displayed_document_id: id })
  })
}

test('reading the saved document leaves an existing editor draft intact', async ({ page }) => {
  await workspace(page, false)
  const draft = { owner: 'agent:7', title: 'Unsaved title', folder: '', content: '<p>Private unsaved draft</p>', keywords: [], globalAccess: 0, sharing: {} }
  const key = 'galaris:document-draft:null:doc-b'
  const saved = JSON.stringify({ revision: 3, draft, base: { ...draft, content: '<p>Initial document body</p>' } })
  await page.evaluate(({ key, saved }) => sessionStorage.setItem(key, saved), { key, saved })
  await openFromSearch(page)
  await expect(page.locator('.chat-document-pane')).not.toContainText('Private unsaved draft')
  await page.getByRole('button', { name: 'Close working document' }).click()
  expect(await page.evaluate(key => sessionStorage.getItem(key), key)).toBe(saved)
})

test('mobile document search opens a dialog and leaves the chat without an integrated document', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await workspace(page)
  const draft = page.locator('.conversation-pane textarea')
  await draft.fill('Keep the mobile conversation')
  await page.getByRole('button', { name: 'Search accessible documents', exact: true }).click()
  await page.getByLabel('Open document Off-list document', { exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toHaveCount(1)
  await expect(dialog).toContainText('Initial document body')
  await expect(page.locator('.chat-document-pane')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Chat and document/ })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(draft).toHaveValue('Keep the mobile conversation')
  await expect(page.getByRole('button', { name: /^(Collapse|Open) conversations and linked items$/ })).toHaveCount(0)
  await page.getByRole('button', { name: 'Details', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Back to conversation', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Back to conversation', exact: true }).click()
  await expect(draft).toHaveValue('Keep the mobile conversation')
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(1)
  expect(state.writes[0]).not.toHaveProperty('displayed_document_id')
})

test('the full document editor saves changes before sending its visible reference and stops sending it after closing', async ({ page }) => {
  const state = await workspace(page)
  await openFromSearch(page)
  const pane = page.locator('.chat-document-pane')
  await expect(pane.getByRole('textbox', { name: 'Title', exact: true })).toBeEditable()
  const content = pane.locator('.ck-editor__editable')
  await expect(content).toBeEditable()
  await content.fill('Document edited from the conversation')
  const draft = page.locator('.conversation-pane textarea')
  await draft.fill('Look at the displayed document')
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(1)
  expect(state.documentWrites.at(-1).payload.text).toContain('Document edited from the conversation')
  expect(state.operations.indexOf('save')).toBeLessThan(state.operations.indexOf('message'))
  expect(state.writes[0]).toMatchObject({ text: 'Look at the displayed document', displayed_document_id: 'doc-b' })
  await page.getByRole('button', { name: 'Search accessible documents', exact: true }).click()
  await page.getByLabel('Open document Off-list document', { exact: true }).click()
  await draft.fill('Still looking at the same document')
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(2)
  expect(state.writes[1]).toMatchObject({ displayed_document_id: 'doc-b' })
  await page.getByRole('button', { name: 'Close working document' }).click()
  await expect(pane).toHaveCount(0)
  await draft.fill('Continue without a document')
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(3)
  expect(state.writes[2]).not.toHaveProperty('displayed_document_id')
})

test('a failed document save preserves the chat draft until saving succeeds', async ({ page }) => {
  const state = await workspace(page)
  await openFromSearch(page)
  let failSave = true
  await page.route('**/api/memory/documents/doc-b', route => {
    if (failSave && route.request().method() === 'PATCH') {
      return route.fulfill({ status: 500, json: { detail: 'Save unavailable' } })
    }
    return route.fallback()
  })
  await page.locator('.chat-document-pane .ck-editor__editable').fill('Keep this document edit')
  const draft = page.locator('.conversation-pane textarea')
  await draft.fill('Keep this message until the document is saved')
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect(page.locator('.q-notification')).toBeVisible()
  await expect(draft).toHaveValue('Keep this message until the document is saved')
  expect(state.writes).toHaveLength(0)
  failSave = false
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(1)
  expect(state.documentWrites.at(-1).payload.text).toContain('Keep this document edit')
  expect(state.writes[0]).toMatchObject({ text: 'Keep this message until the document is saved', displayed_document_id: 'doc-b' })
  await expect(draft).toHaveValue('')
})

test('a late response from the previous document cannot overwrite the selected document', async ({ page }) => {
  await workspace(page)
  await openFromSearch(page)
  let release
  await page.route('**/api/memory/documents/doc-b', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { item: { ...documentFixture, id: 'doc-b', payload: { text: 'Late private body' } }, agent_id: null } })
  })
  await page.evaluate(() => window.testApp.emitSocket('memory.update', { data: { id: 'doc-b', node_kind: 'document', revision: 4 } }))
  await expect.poll(() => Boolean(release)).toBeTruthy()
  await page.getByText('Working documents', { exact: true }).first().click()
  await page.getByLabel('Open document Test document', { exact: true }).click()
  await expect(page.locator('.chat-document-pane')).toContainText('Initial document body')
  release()
  await expect(page.locator('.chat-document-pane')).not.toContainText('Late private body')
  await expect(page.locator('.chat-document-pane')).toContainText('Test document')
  await page.evaluate(() => window.testApp.patchStore('app/chat/stores/chat.ts', 'useChatStore', { viewerAgentId: 99 }))
  await expect(page.locator('.chat-document-pane')).toHaveCount(0)
})

test('layout and viewport changes preserve both contents, draft and updates with the desktop sidebar visible', async ({ page }, testInfo) => {
  const state = await workspace(page)
  await openFromSearch(page)
  const draft = page.locator('.conversation-pane textarea')
  await draft.fill('Keep this draft through layout changes')
  for (const width of [1440, 1024, 1023, 390, 1200]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.locator('.sidebar-mobile-toolbar')).toHaveCount(width < 1024 ? 1 : 0)
    await expect(page.getByRole('button', { name: /^(Collapse|Open) conversations and linked items$/ })).toHaveCount(0)
    if (width < 1024) {
      await expect(page.locator('.chat-document-pane')).toHaveCount(0)
      await expect(page.getByRole('separator', { name: 'Resize chat and document', exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: /^Chat and document/ })).toHaveCount(0)
      await state.update('Updated document body')
      await expect(page.getByRole('dialog')).toContainText('Updated document body')
      await expect(draft).toHaveValue('Keep this draft through layout changes')
      continue
    }
    await expect(page.getByRole('dialog')).toHaveCount(0)
    for (const layout of ['stacked', 'side by side']) {
      await page.locator('.chat-document-toolbar').getByRole('button', { name: `Chat and document ${layout}` }).click()
      await expect(page.locator('#chat-sidebar-content')).toBeVisible()
      await state.update('Updated document body')
      await expect(page.locator('.chat-document-pane')).toContainText('Updated document body')
      await visibleTogether(page)
      await expect(draft).toHaveValue('Keep this draft through layout changes')
    }
    await page.screenshot({ path: testInfo.outputPath(`workspace-${width}.png`) })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await expect(page.getByRole('separator', { name: 'Resize chat and document', exact: true })).toHaveAttribute('aria-orientation', 'vertical')
  await visibleTogether(page)
  await page.getByRole('button', { name: 'Close working document' }).click()
  await expect(draft).toHaveValue('Keep this draft through layout changes')
  await openFromSearch(page)
})

for (const width of [1440, 1024]) {
  for (const layout of ['side by side', 'stacked']) {
    test(`the ${layout} divider resizes both panes and preserves editing at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 })
      await workspace(page)
      await openFromSearch(page)
      await page.getByRole('button', { name: `Chat and document ${layout}` }).click()
      const separator = page.getByRole('separator', { name: 'Resize chat and document', exact: true })
      const stacked = layout === 'stacked' || width === 1024
      await expect(separator).toHaveAttribute('aria-orientation', stacked ? 'horizontal' : 'vertical')
      const draft = page.locator('.conversation-pane textarea')
      await draft.fill('Keep this chat draft while resizing')
      const editor = page.locator('.chat-document-pane .ck-editor__editable')
      await editor.fill('Keep editing this document while resizing\n'.repeat(80))
      const dimension = async () => {
        const bounds = await page.locator('.conversation-pane').boundingBox()
        return stacked ? bounds.height : bounds.width
      }
      const initial = await dimension()
      await page.locator('.chat-document-content').evaluate(element => { element.scrollTop = 650 })
      const handle = await separator.boundingBox()
      const start = { x: handle.x + handle.width / 2, y: handle.y + handle.height / 2 }
      const end = { x: start.x + (stacked ? 0 : -60), y: start.y + (stacked ? 60 : 0) }
      if (width === 1024) {
        const touch = await page.context().newCDPSession(page)
        await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [start] })
        await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [end] })
        await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
        await touch.detach()
      } else {
        await page.mouse.move(start.x, start.y)
        await page.mouse.down()
        await page.mouse.move(end.x, end.y, { steps: 6 })
        await page.mouse.up()
      }
      if (stacked) await expect.poll(dimension).toBeGreaterThan(initial + 25)
      else await expect.poll(dimension).toBeLessThan(initial - 25)
      const toolbar = page.locator('.chat-document-pane').getByRole('toolbar', { name: 'Editor toolbar', exact: true })
      await expect.poll(() => toolbar.evaluate(element => {
        const toolbar = element.getBoundingClientRect()
        const editor = element.closest('.ck-editor').getBoundingClientRect()
        return Math.max(Math.abs(toolbar.left - editor.left), Math.abs(toolbar.right - editor.right))
      })).toBeLessThanOrEqual(1)
      const dragged = await dimension()
      await separator.press(stacked ? 'ArrowUp' : 'ArrowRight')
      if (stacked) await expect.poll(dimension).toBeLessThan(dragged)
      else await expect.poll(dimension).toBeGreaterThan(dragged)
      const resized = await dimension()
      await page.getByRole('button', { name: `Chat and document ${layout === 'stacked' ? 'side by side' : 'stacked'}` }).click()
      await page.getByRole('button', { name: `Chat and document ${layout}` }).click()
      await expect.poll(dimension).toBeCloseTo(resized, 0)
      await expect(draft).toHaveValue('Keep this chat draft while resizing')
      await expect(editor).toContainText('Keep editing this document while resizing')
      await expect(editor).toBeEditable()
      if (!stacked) {
        await separator.press('End')
        await expect.poll(async () => (await page.locator('.chat-document-pane').boundingBox()).width).toBeGreaterThanOrEqual(560)
        await expect(editor).toHaveAttribute('data-document-layout', 'full')
      }
      await page.screenshot({ path: testInfo.outputPath('resized-workspace.png') })
    })
  }
}

test('denied document and reconnect recover authorized current content while chat remains usable', async ({ page }) => {
  const state = await workspace(page)
  await openFromSearch(page)
  await page.locator('.conversation-pane textarea').fill('Draft survives connection loss')
  state.deny(true)
  await state.update('Denied document body')
  await expect(page.locator('.chat-document-pane')).not.toContainText('Initial document body')
  await expect(page.locator('.chat-document-pane').getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  state.deny(false)
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect(page.locator('.chat-document-pane')).toContainText('Denied document body')
  await expect(page.locator('.conversation-pane textarea')).toHaveValue('Draft survives connection loss')
  await page.evaluate(() => window.testApp.emitSocket('memory.delete', { data: { id: 'doc-b', node_kind: 'document' } }))
  await expect(page.locator('.chat-document-pane')).not.toContainText('Denied document body')
  await expect(page.locator('.conversation-pane textarea')).toBeEditable()
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(1)
  expect(state.writes[0]).not.toHaveProperty('displayed_document_id')
})

test('creation cancellation and rejection preserve chat without opening a fictitious document', async ({ page }) => {
  await workspace(page)
  await page.locator('.conversation-pane textarea').fill('Keep draft')
  await page.getByText('Working documents', { exact: true }).first().click()
  await page.getByRole('button', { name: 'Create document', exact: true }).click()
  await page.getByRole('textbox', { name: 'Title', exact: true }).fill('Cancelled')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.chat-document-pane')).toHaveCount(0)
  await page.route('**/api/chat/rooms/room-a/documents', route => route.fulfill({ status: 403, json: { detail: 'Creation forbidden' } }))
  await page.getByRole('button', { name: 'Create document', exact: true }).click()
  await page.getByRole('textbox', { name: 'Title', exact: true }).fill('Rejected')
  await page.getByRole('dialog').getByRole('button', { name: 'Create document', exact: true }).click()
  await expect(page.getByText('Creation forbidden')).toBeVisible()
  await expect(page.locator('.chat-document-pane')).toHaveCount(0)
  await expect(page.locator('.conversation-pane textarea')).toHaveValue('Keep draft')
})

test('search errors and empty results stay explicit and late results cannot replace a new search', async ({ page }) => {
  await workspace(page)
  let release
  await page.route('**/api/memory/documents/library', async route => {
    const { query } = route.request().postDataJSON()
    if (query === 'old') {
      await new Promise(resolve => { release = resolve })
      return route.fulfill({ json: { entries: [{ item: { id: 'old-document', title: 'Obsolete result' } }], total: 1 } })
    }
    if (query === 'error') return route.fulfill({ status: 500, json: { detail: 'Search unavailable' } })
    return route.fulfill({ json: { entries: [], total: 0 } })
  })
  await page.getByRole('button', { name: 'Search accessible documents', exact: true }).click()
  const query = page.getByRole('textbox', { name: 'Search accessible documents' })
  await query.fill('old')
  await expect.poll(() => Boolean(release)).toBeTruthy()
  await query.fill('new')
  await expect(page.getByText('No accessible documents found.')).toBeVisible()
  release()
  await expect(page.getByText('Obsolete result')).toHaveCount(0)
  await query.fill('error')
  await expect(page.getByText('Unable to search documents.')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.locator('.conversation-pane textarea')).toBeEditable()
})

async function visibleTogether(page) {
  const chat = await page.locator('.conversation-pane').boundingBox()
  const document = await page.locator('.chat-document-pane').boundingBox()
  const viewport = page.viewportSize()
  if (await page.getByRole('separator', { name: 'Resize chat and document', exact: true }).getAttribute('aria-orientation') === 'vertical') {
    expect(document.width).toBeGreaterThanOrEqual(560)
  }
  for (const box of [chat, document]) {
    expect(box.width).toBeGreaterThan(0)
    expect(box.height).toBeGreaterThan(100)
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 1)
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1)
  }
  expect(chat.x + chat.width <= document.x + 1 || chat.y + chat.height <= document.y + 1).toBeTruthy()
  await expect(page.locator('.chat-document-content')).toContainText('document body')
  await page.locator('.chat-document-content p').filter({ hasText: 'document body' }).scrollIntoViewIfNeeded()
  await expect(page.locator('.chat-document-content p').filter({ hasText: 'document body' })).toBeInViewport()
  await expect(page.locator('.conversation-pane textarea')).toBeVisible()
}

for (const access of ['list', 'create', 'search']) {
  for (const layout of ['side by side', 'stacked']) {
    test(`${access}, ${layout}, visible sidebar preserves chat and live document`, async ({ page }) => {
      const state = await workspace(page)
      const draft = page.locator('.conversation-pane textarea')
      await draft.fill('Draft to preserve')
      if (access === 'search') {
        await page.getByRole('button', { name: 'Search accessible documents', exact: true }).click()
        await page.getByRole('textbox', { name: 'Search accessible documents' }).fill('Test')
        await page.getByLabel('Open document Off-list document', { exact: true }).click()
      } else {
        await page.getByText('Working documents', { exact: true }).first().click()
        if (access === 'create') {
          await page.getByRole('button', { name: 'Create document', exact: true }).click()
          await page.getByRole('textbox', { name: 'Title', exact: true }).fill('Created document')
          await page.getByRole('dialog').getByRole('button', { name: 'Create document', exact: true }).click()
        } else await page.getByLabel('Open document Test document', { exact: true }).click()
      }
      await expect(page.locator('.chat-document-pane')).toContainText('Initial document body')
      await page.getByRole('button', { name: `Chat and document ${layout}`, exact: true }).press('Enter')
      await expect(page.locator('#chat-sidebar-content')).toBeVisible()
      await visibleTogether(page)
      await state.update('Updated document body')
      await expect(page.locator('.chat-document-pane')).toContainText('Updated document body')
      await expect(draft).toHaveValue('Draft to preserve')
      await state.update('Unrelated body', 'other-document')
      await expect(page.locator('.chat-document-pane')).toContainText('Updated document body')
      await page.getByRole('button', { name: 'Post', exact: true }).click()
      await expect.poll(() => state.writes.length).toBe(1)
      await expect(page.locator('.chat-document-pane')).toBeVisible()
    })
  }
}
