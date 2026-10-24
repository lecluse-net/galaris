import { test, expect } from '@playwright/test'
import { createDocument } from '../documents.mjs'
import { collectPageErrors } from '../page-errors.mjs'

test('Documents persists checklist state and converses in a room also available in Chat', async ({ page, request }) => {
  const errors = collectPageErrors(page)
  const displayedRooms = []
  const documentConversationRequests = []
  page.on('request', request => {
    if (/\/api\/chat\/documents\/[^/]+\/conversation$/.test(request.url())) documentConversationRequests.push(request.url())
  })
  page.on('websocket', socket => socket.on('framesent', ({ payload }) => {
    if (typeof payload !== 'string' || !payload.startsWith('42[')) return
    const [event, data] = JSON.parse(payload.slice(2))
    if (event === 'room.display') displayedRooms.push(data.room)
  }))
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login'); await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const created = await createDocument(request, { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic authoring report', media_type: 'text/html',
    payload: { text: '<h1>Report</h1><h2>Review</h2><p>Review draft</p>' },
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const document = await created.json()
  const roomResponse = await request.get(`/api/chat/rooms/${fixture.rooms[0]}`, { headers })
  expect(roomResponse.ok()).toBeTruthy()
  const room = await roomResponse.json()
  await errors.settle()
  await page.goto(`/documents?document_id=${document.id}`)
  const editor = page.locator('[data-editor-surface]')
  await expect(editor).toContainText('Review draft')
  const conversationToggle = page.getByRole('toolbar', { name: /^(Content|Contenu)$/ }).getByRole('button', { name: 'Conversation', exact: true })
  await expect(conversationToggle).toHaveAttribute('aria-expanded', 'false')
  expect(documentConversationRequests).toEqual([])
  await editor.locator('p').click()
  await page.getByRole('button', { name: /^(Checklist|Liste à cocher)$/ }).click()
  await editor.getByRole('checkbox', { name: 'Review draft', exact: true }).check()
  await expect.poll(async () => (await (await request.get(`/api/documents/${document.id}`, { headers })).json()).item.payload.text).toContain('data-checked="true"')
  await page.reload()
  await expect(editor.getByRole('checkbox', { name: 'Review draft', exact: true })).toBeChecked()
  await page.getByRole('button', { name: /^(Document outline|Plan du document)$/ }).click()
  const outline = page.getByRole('navigation', { name: /^(Document outline|Plan du document)$/ })
  await outline.getByText('Review', { exact: true }).click()
  await expect(outline.getByText('Report', { exact: true })).toBeVisible()
  await editor.locator('p').click()
  await page.keyboard.press('Home')
  await page.keyboard.press('Shift+End')
  await expect.poll(() => page.evaluate(() => window.getSelection().toString())).toBe('Review draft')
  await conversationToggle.click()
  const panel = page.getByRole('region', { name: 'Conversation', exact: true })
  await panel.getByRole('combobox').click()
  const roomLabel = page.getByText(room.label, { exact: true }).and(page.locator('.q-item__label:not(.q-item__label--caption)'))
  await page.getByRole('option').filter({ has: roomLabel }).click()
  await expect.poll(() => displayedRooms.at(-1)).toBe(`ChatRoom:${room.id}`)
  await panel.locator('textarea').fill('Synthetic document conversation')
  const sending = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith(`/api/chat/rooms/${room.id}/messages`))
  await panel.locator('textarea').press('Enter')
  const context = (await sending).postDataJSON()
  expect(context).toMatchObject({ displayed_document_id: document.id, document_focus: {
    surface: 'rendered', selection: { start: 12, end: 24, text: 'Review draft', truncated: false },
  } })
  await expect(panel.locator('.message-timeline')).toContainText('Réponse progressive', { timeout: 40_000 })
  expect((await request.post(`/api/__test/release/${room.id}`)).ok()).toBeTruthy()
  await expect(panel.locator('.message-timeline')).toContainText('Réponse progressive terminée.')
  await expect.poll(async () => (await (await request.get(`/api/chat/rooms/${room.id}`, { headers })).json()).unread_count).toBe(0)
  await page.screenshot({ path: test.info().outputPath('document-with-outline-and-conversation.png') })
  await expect.poll(async () => (await (await request.get(`/api/chat/documents/${document.id}/conversation`, { headers })).json()).room_id).toBe(room.id)
  const conversationRequestsBeforeReload = documentConversationRequests.length
  await page.reload()
  await expect(editor).toContainText('Review draft')
  await expect(conversationToggle).toHaveAttribute('aria-expanded', 'false')
  await expect(panel).not.toBeVisible()
  expect(documentConversationRequests).toHaveLength(conversationRequestsBeforeReload)
  await conversationToggle.click()
  await expect(panel.locator('.message-timeline')).toContainText('Synthetic document conversation')
  await expect(panel.locator('.message-timeline')).toContainText('Réponse progressive terminée.')
  await errors.settle()
  await page.goto(`/chat?room=${room.id}`)
  await expect(page.locator('.conversation-pane')).toContainText('Synthetic document conversation')
  await expect(page.locator('.conversation-pane')).toContainText('Réponse progressive terminée.')
  expect(errors()).toEqual([])
})
