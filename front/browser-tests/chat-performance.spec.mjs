import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5AAAAABJRU5ErkJggg==', 'base64')
const message = index => ({ id: `message-${index}`, external_id: `message-${index}`,
  text: `Synthetic message ${index}`, files: [], is_mine: false,
  sender: { display_name: 'Participant', is_ai: false }, created_at: '2026-10-01T12:00:00Z' })
const live = (text, active = true) => ({ room_id: 'performance-room', round_id: 'performance-round',
  active, success: true, topic_id: null, last_sequence: 1,
  ai_result: { prompt: '', system_prompt: '', result: text, messages: [{ type: 'text', content: text }],
    tools_used: [], cost: 0, execution_time: 0, success: true } })

async function timeline(page, messages) {
  await jsonRoute(page, '**/api/chat/rooms/*/speech/status*', { available_agent_ids: [] })
  await mount(page, 'app/chat/components/MessageTimeline.vue', {
    containerStyle: { height: '480px', overflow: 'auto' },
    props: { roomId: 'performance-room', messages, activity: [], liveRound: null,
      agentId: 7, agentName: 'Agent', showAgentAvatars: false },
  })
}

async function scrollTo(page, end) {
  await page.locator('.q-page-container').evaluate((element, end) => {
    element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: end ? 1 : -1 }))
    element.scrollTop = end ? element.scrollHeight : 0
  }, end)
}

test('stream fragments leave historic message preparation unchanged', async ({ page }, testInfo) => {
  await timeline(page, [])
  await page.evaluate(async items => {
    window.historyNameReads = 0
    for (const item of items) Object.defineProperty(item.sender, 'display_name', {
      get() { window.historyNameReads++; return 'Participant' }, enumerable: true,
    })
    await window.testApp.setProps({ messages: items })
  }, Array.from({ length: 1000 }, (_, index) => message(index)))
  await page.evaluate(round => window.testApp.setProps({ liveRound: round }), live('Initial response'))
  const before = await page.evaluate(() => window.historyNameReads)
  for (let index = 0; index < 20; index++) {
    await page.evaluate(round => window.testApp.setProps({ liveRound: round }), live(`Response fragment ${index}`))
  }
  const repeated = await page.evaluate(() => window.historyNameReads) - before
  await testInfo.attach('history-preparation', { body: JSON.stringify({ messages: 1000, fragments: 20, repeatedNameReads: repeated }), contentType: 'application/json' })
  expect(repeated).toBeLessThan(100)
  await page.evaluate(round => window.testApp.setProps({ liveRound: round }), live('Complete final response', false))
  await expect(page.locator('.message-bubble--live')).toContainText('Complete final response')
})

test('streamed Markdown batches rendering and flushes the complete final content', async ({ page }, testInfo) => {
  await mount(page, 'app/chat/components/SafeMessageContent.vue', { props: { content: 'Initial', streaming: true } })
  await page.clock.install()
  await page.locator('.safe-message-content').evaluate(element => {
    window.markdownRenders = 0
    window.markdownObserver = new MutationObserver(() => { window.markdownRenders++ })
    window.markdownObserver.observe(element, { childList: true, subtree: true, characterData: true })
  })
  for (let index = 0; index < 40; index++) {
    await page.evaluate(content => window.testApp.setProps({ content }), `Initial${' word'.repeat(index + 1)}`)
    await page.clock.runFor(5)
  }
  const updates = await page.evaluate(() => window.markdownRenders)
  await testInfo.attach('markdown-rendering', { body: JSON.stringify({ fragments: 40, elapsedMs: 200, renders: updates }), contentType: 'application/json' })
  expect(updates).toBeLessThan(15)
  await page.evaluate(() => window.testApp.setProps({ streaming: false, content: '# Final response\n\nAll **content** is present.\n\n```text\nfinal-code\n```' }))
  await expect(page.getByRole('heading', { name: 'Final response', exact: true })).toBeVisible()
  await expect(page.locator('.safe-message-content')).toContainText('All content is present.')
  await expect(page.locator('.source-code')).toContainText('final-code')
  await page.evaluate(() => window.markdownObserver.disconnect())
})

test('revisiting a virtual message reuses its resource metadata and thumbnail', async ({ page }, testInfo) => {
  const reads = { metadata: 0, thumbnail: 0 }
  await page.route('**/api/chat/rooms/*/messages/message-0/previews**', route => {
    const image = new URL(route.request().url()).pathname.endsWith('/image')
    reads[image ? 'thumbnail' : 'metadata']++
    return route.fulfill(image ? { contentType: 'image/png', body: pixel } : { json: [{
      uri: 'https://example.test/synthetic', kind: 'web', title: 'Synthetic resource', description: 'Synthetic description',
      subtitle: '', image_available: true, download_available: false, open_mode: 'external',
      external_url: 'https://example.test/synthetic', media_type: 'text/html', metadata: {},
    }] })
  })
  const items = Array.from({ length: 400 }, (_, index) => message(index))
  items[0].text = 'https://example.test/synthetic'
  await timeline(page, items)
  await expect(page.locator('.resource-preview-card img')).toHaveJSProperty('naturalWidth', 1)
  await scrollTo(page, true)
  await expect(page.locator('[data-message-id="message-0"]')).toHaveCount(0)
  await scrollTo(page, false)
  await expect(page.locator('.resource-preview-card img')).toHaveJSProperty('naturalWidth', 1)
  await testInfo.attach('preview-reads', { body: JSON.stringify(reads), contentType: 'application/json' })
  expect(reads).toEqual({ metadata: 1, thumbnail: 1 })
})

test('browsing attachments bounds retained blob bytes and reloads an evicted preview', async ({ page }, testInfo) => {
  const reads = new Map()
  const payload = Buffer.concat([pixel, Buffer.alloc(1024 * 1024 - pixel.length)])
  await page.route('**/api/chat/rooms/*/files/*', route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1)
    reads.set(id, (reads.get(id) ?? 0) + 1)
    return route.fulfill({ contentType: 'image/png', body: payload })
  })
  await page.addInitScript(() => {
    const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL)
    window.retainedMedia = new Map()
    URL.createObjectURL = blob => { const url = create(blob); if (blob.type === 'image/png') window.retainedMedia.set(url, blob.size); return url }
    URL.revokeObjectURL = url => { window.retainedMedia.delete(url); revoke(url) }
  })
  const items = Array.from({ length: 40 }, (_, index) => ({ ...message(index),
    text: 'Synthetic context. '.repeat(40), files: [{ id: `file-${index}`, name: `file-${index}.png`, mime_type: 'image/png', kind: 'image' }] }))
  await timeline(page, items)
  for (let index = 0; index < 40; index++) {
    const attachment = page.locator(`[data-attachment-id="file-${index}"]`)
    await attachment.scrollIntoViewIfNeeded()
    await expect(attachment.locator('img')).toHaveJSProperty('naturalWidth', 1)
  }
  const bytes = await page.evaluate(() => [...window.retainedMedia.values()].reduce((sum, size) => sum + size, 0))
  await testInfo.attach('retained-media', { body: JSON.stringify({ visited: 40, bytes }), contentType: 'application/json' })
  expect(bytes).toBeLessThanOrEqual(32 * 1024 * 1024)
  await page.locator('[data-attachment-id="file-0"]').scrollIntoViewIfNeeded()
  await expect(page.locator('[data-attachment-id="file-0"] img')).toHaveJSProperty('naturalWidth', 1)
  expect(reads.get('file-0')).toBe(2)
})

test('cached resources expire, invalidate while unmounted and isolate agents and sessions', async ({ page }) => {
  let revision = 1
  const reads = []
  await page.route('**/api/chat/rooms/*/messages/message-0/previews**', route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/image')) return route.fulfill({ contentType: 'image/png', body: pixel })
    const viewer = url.searchParams.get('agent_id') ?? 'human'
    reads.push(viewer)
    return route.fulfill({ json: [{ uri: 'https://example.test/synthetic', kind: 'web',
      title: `Resource ${revision} for ${viewer}`, description: 'Synthetic resource description',
      subtitle: '', image_available: true, download_available: false, open_mode: 'external',
      external_url: 'https://example.test/synthetic', media_type: 'text/html', metadata: {} }] })
  })
  const items = Array.from({ length: 400 }, (_, index) => message(index))
  items[0].text = 'https://example.test/synthetic'
  await timeline(page, items)
  await expect(page.getByText('Resource 1 for human', { exact: true })).toBeVisible()
  const away = async () => {
    await scrollTo(page, true)
    await expect(page.locator('[data-message-id="message-0"]')).toHaveCount(0)
  }
  await away()
  await page.clock.setFixedTime(new Date(Date.now() + 31_000))
  revision = 2
  await scrollTo(page, false)
  await expect(page.getByText('Resource 2 for human', { exact: true })).toBeVisible()
  expect(reads).toEqual(['human', 'human'])
  await away()
  revision = 3
  await page.evaluate(() => window.testApp.emitSocket('document.update', {
    data: { id: 'synthetic-document', node_kind: 'document', revision: 3 },
  }))
  await scrollTo(page, false)
  await expect(page.getByText('Resource 3 for human', { exact: true })).toBeVisible()
  expect(reads).toHaveLength(3)
  await page.evaluate(() => window.testApp.setProps({ viewerAgentId: 9 }))
  await expect(page.getByText('Resource 3 for 9', { exact: true })).toBeVisible()
  expect(reads.at(-1)).toBe('9')
  revision = 4
  await page.evaluate(() => window.testApp.emitSocket('connect'))
  await expect(page.getByText('Resource 4 for 9', { exact: true })).toBeVisible()
  await page.evaluate(async () => {
    const { AUTH_TOKEN_CHANGED_EVENT } = await import('/core/api.ts')
    window.dispatchEvent(new CustomEvent(AUTH_TOKEN_CHANGED_EVENT, { detail: null }))
  })
  await expect(page.locator('.resource-preview-card')).toHaveCount(0)
  revision = 5
  await page.evaluate(async () => {
    const { AUTH_TOKEN_CHANGED_EVENT } = await import('/core/api.ts')
    window.dispatchEvent(new CustomEvent(AUTH_TOKEN_CHANGED_EVENT, { detail: 'synthetic-next-session' }))
  })
  await expect(page.getByText('Resource 5 for 9', { exact: true })).toBeVisible()
})

test('a resource invalidation during a pending read cannot restore obsolete metadata', async ({ page }) => {
  let reads = 0, release
  const held = new Promise(resolve => { release = resolve })
  await page.route('**/api/chat/rooms/*/messages/message-0/previews**', async route => {
    const initial = ++reads === 1
    if (initial) await held
    await route.fulfill({ json: [{ uri: 'document://00000000-0000-4000-8000-000000000001',
      kind: 'document', title: 'Synthetic document', deleted: !initial, description: '', subtitle: '',
      image_available: false, download_available: false, open_mode: 'inline', media_type: 'text/html', metadata: {} }] }).catch(() => {})
  })
  await timeline(page, [{ ...message(0), text: 'document://00000000-0000-4000-8000-000000000001' }])
  await expect.poll(() => reads).toBe(1)
  await page.evaluate(() => window.testApp.emitSocket('document.delete', {
    data: { id: '00000000-0000-4000-8000-000000000001', node_kind: 'document' },
  }))
  await expect(page.getByText('Document deleted', { exact: false })).toBeVisible()
  release()
  await expect(page.getByText('Document deleted', { exact: false })).toBeVisible()
  await expect(page.locator('.resource-preview-card button')).toHaveCount(0)
})

test('a paused empty response keeps its controls and a durable handoff keeps authoritative message text', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/rooms/*/speech/status*', { available_agent_ids: [] })
  const activity = { id: 'performance-round', status: 'PAUSED', response_message_id: null,
    message_ids: ['message-0'], available_actions: ['resume', 'stop'], attempt: 1,
    tools_used: [], execution_time: 0, cost: 0 }
  const input = { ...message(0), is_mine: true }
  await mount(page, 'app/chat/components/MessageTimeline.vue', { privileges: ['CHAT_SEND'], props: {
    roomId: 'performance-room', agentId: 7, agentName: 'Agent', messages: [input],
    activity: [activity], liveRound: live('', false), showAgentAvatars: false,
  } })
  await expect(page.getByRole('button', { name: 'Resume response', exact: true })).toBeVisible()
  const durable = { ...message(1), text: 'Authoritative saved response' }
  await page.evaluate(({ input, activity, durable, round }) => window.testApp.setProps({
    messages: [input, durable], activity: [{ ...activity, status: 'DONE', response_message_id: durable.id, message_ids: [input.id] }],
    liveRound: round,
  }), { input, activity, durable, round: live('Obsolete streamed response') })
  await expect(page.locator('[data-message-id="message-1"]')).toContainText('Authoritative saved response')
  await expect(page.locator('[data-message-id="message-0"]')).toContainText('Synthetic message 0')
  await expect(page.locator('[data-message-id="message-1"]')).toHaveCount(1)
  // Execution details may retain the richer streamed snapshot; the message body
  // must always use the canonical durable text during that handoff.
  await expect(page.locator('[data-message-id="message-1"] .message-text')).not.toContainText('Obsolete streamed response')
  await expect.poll(() => page.evaluate(() => window.testApp.events.some(event => event.name === 'messageVisible' && event.value === 'message-1'))).toBe(true)
})
