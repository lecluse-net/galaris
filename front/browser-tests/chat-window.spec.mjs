import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const message = index => ({ id: `message-${index}`, external_id: `message-${index}`,
  text: `Synthetic message ${index}\n\n${index % 7 === 0 ? 'A longer paragraph in the conversation. '.repeat(30) : 'Short reply.'}`,
  files: [], sender: { display_name: 'Participant', is_ai: false }, is_mine: false,
  created_at: '2026-10-01T12:00:00Z' })
const messages = count => Array.from({ length: count }, (_, index) => message(index))

async function timeline(page, items) {
  await jsonRoute(page, '**/api/chat/rooms/*/speech/status*', { available_agent_ids: [] })
  await mount(page, 'app/chat/components/MessageTimeline.vue', {
    containerStyle: { height: '480px', overflow: 'auto' },
    props: { roomId: 'window-room', messages: items, activity: [], liveRound: null,
      agentId: 7, agentName: 'Agent', showAgentAvatars: false },
  })
  return page.locator('.q-page-container')
}

async function scrollTo(page, position) {
  await page.locator('.q-page-container').evaluate((element, position) => {
    element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: position === 'start' ? -1 : 1 }))
    element.scrollTop = position === 'start' ? 0 : position === 'end' ? element.scrollHeight : element.scrollHeight / 2
  }, position)
}

async function anchor(page) {
  return page.locator('.q-page-container').evaluate(container => {
    const top = container.getBoundingClientRect().top
    const row = [...container.querySelectorAll('[data-message-id]')]
      .find(row => row.getBoundingClientRect().bottom > top + 24 && row.getBoundingClientRect().top < top + container.clientHeight)
    return row ? { id: row.dataset.messageId, offset: row.getBoundingClientRect().top - top } : null
  })
}

test('long chat histories bound mounted bubbles and keep both ends, replies and read visibility reachable', async ({ page }, testInfo) => {
  await timeline(page, messages(1000))
  await expect(page.locator('[data-message-id="message-0"]')).toContainText('Synthetic message 0')
  const initialRows = await page.locator('.message-row').count()
  await testInfo.attach('mounted-history', { body: JSON.stringify({ loaded: 1000, mounted: initialRows }), contentType: 'application/json' })
  expect(initialRows).toBeLessThan(100)
  await scrollTo(page, 'end')
  const last = page.locator('[data-message-id="message-999"]')
  await expect(last).toContainText('Synthetic message 999')
  await expect.poll(() => page.evaluate(() => window.testApp.events.some(event => event.name === 'messageVisible' && event.value === 'message-999'))).toBe(true)
  await last.getByRole('button', { name: 'Reply', exact: true }).click()
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'reply').at(-1).value.id)).toBe('message-999')
  await scrollTo(page, 'start')
  await expect(page.locator('[data-message-id="message-0"]')).toContainText('Synthetic message 0')
  expect(await page.locator('.message-row').count()).toBeLessThan(100)
})

test('variable-height history preserves its reading anchor through prepend, streaming and a narrower viewport', async ({ page }) => {
  const items = messages(400)
  await timeline(page, items)
  await scrollTo(page, 'middle')
  await expect.poll(async () => (await anchor(page))?.id).not.toBe('message-0')
  // Let asynchronous Markdown and height observers finish before capturing the reading position.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const before = await anchor(page)
  expect(before).not.toBeNull()
  await page.evaluate(messages => window.testApp.setProps({ messages }), [
    ...Array.from({ length: 50 }, (_, index) => message(index - 50)), ...items,
  ])
  const original = page.locator(`[data-message-id="${before.id}"]`)
  await expect(original).toBeVisible()
  const offset = () => original.evaluate(element => element.getBoundingClientRect().top
    - element.closest('.q-page-container').getBoundingClientRect().top)
  await expect.poll(async () => Math.abs(await offset() - before.offset)).toBeLessThan(4)
  await page.evaluate(() => window.testApp.setProps({ liveRound: {
    room_id: 'window-room', round_id: 'live-round', topic_id: null, active: true, success: true,
    last_sequence: 1, ai_result: { prompt: '', system_prompt: '', result: '',
      messages: [{ type: 'text', content: 'Progress outside the reading window. '.repeat(30) }],
      tools_used: [], cost: 0, execution_time: 0, success: true },
  } }))
  await expect.poll(async () => Math.abs(await offset() - before.offset)).toBeLessThan(4)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(async () => Math.abs(await offset() - before.offset)).toBeLessThan(4)
  await scrollTo(page, 'end')
  await expect(page.locator('.message-bubble--live')).toContainText('Progress outside the reading window.')
  await expect.poll(() => page.locator('.q-page-container').evaluate(element => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThan(5)
  await page.locator('.q-page-container').evaluate(element => { element.style.height = '280px' })
  await expect.poll(() => page.locator('.q-page-container').evaluate(element => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThan(5)
})

test('a focused message and its selection survive leaving the rendering window; keyboard navigation reaches the ends', async ({ page }) => {
  await timeline(page, messages(400))
  const first = page.locator('[data-message-id="message-0"]')
  const reply = first.getByRole('button', { name: 'Reply', exact: true })
  await reply.focus()
  await scrollTo(page, 'end')
  await expect(reply).toBeFocused()
  expect(await page.locator('.message-row').count()).toBeLessThan(100)
  await scrollTo(page, 'start')
  await first.locator('.message-text').evaluate(element => {
    const range = document.createRange()
    range.selectNodeContents(element)
    const selection = window.getSelection()
    selection.removeAllRanges(); selection.addRange(range)
  })
  const selected = await page.evaluate(() => window.getSelection().toString())
  await scrollTo(page, 'end')
  expect(await page.evaluate(() => window.getSelection().toString())).toBe(selected)
  await page.evaluate(() => window.getSelection().removeAllRanges())
  const history = page.getByRole('region', { name: 'Message history', exact: true })
  await history.focus()
  await history.press('Home')
  await expect(first).toBeVisible()
  await history.press('End')
  await expect(page.locator('[data-message-id="message-399"]')).toBeVisible()
  await history.press('Control+f')
  await expect(page.locator('[data-message-id]')).toHaveCount(400)
  await history.press('Escape')
  await expect.poll(() => page.locator('.message-row').count()).toBeLessThan(100)
})

for (const surface of ['chat', 'discussion']) for (const width of [1440, 390]) {
  test(`${surface} paginates across the rendering threshold, preserves history and reopens at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const room = { id: 'window-room', label: 'Synthetic conversation', agent_id: 7,
      agent_name: 'Agent', agent_active: false, source: null, writable: true,
      members: [], muted: false, archived: false, unread_count: 0, conversation_type: 'text' }
    await jsonRoute(page, '**/api/chat/rooms/window-room', room)
    await jsonRoute(page, '**/api/chat/rooms/window-room/speech/status*', { available_agent_ids: [] })
    let reads = 0
    await page.route('**/api/chat/rooms/window-room/messages?*', route => {
      const number = Number(new URL(route.request().url()).searchParams.get('page'))
      reads++
      return route.fulfill({ json: { items: Array.from({ length: 50 }, (_, index) => {
        const n = 200 - number * 50 + index
        return { ...message(n), room_id: room.id, created_at: new Date(Date.UTC(2026, 9, 1) + n * 1000).toISOString() }
      }).reverse(), total: 200, page: number, history_has_more: false } })
    })
    if (surface === 'chat') {
      await jsonRoute(page, '**/api/chat/status', { enabled: true, chat_enabled: true, max_attachment_bytes: 1000000 })
      await jsonRoute(page, '**/api/chat/rooms?*', { items: [room], total: 1 })
      await jsonRoute(page, '**/api/chat/rooms/window-room/activity?*', { items: [], total: 0 })
      await jsonRoute(page, '**/api/chat/rooms/window-room/read', {})
      await jsonRoute(page, '**/api/chat/rooms/window-room/commands', { commands: [] })
      await jsonRoute(page, '**/api/chat/inbox', { unread_count: 0 })
      await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
      await jsonRoute(page, '**/api/chat/agents/7/avatar', {})
    }
    const open = () => surface === 'chat'
      ? mount(page, 'app/chat/pages/index.vue', { route: '/chat?room=window-room', privileges: ['CHAT_SEND'] })
      : mount(page, 'resourceDetails.vue', { props: { target: { kind: 'room', id: room.id, title: room.label } } })
    await open()
    const scroll = page.locator(surface === 'chat' ? '.message-scroll .q-scrollarea__container' : '.room-discussion .q-scrollarea__container')
    const last = page.locator('[data-message-id="message-199"]')
    await expect(last).toBeInViewport()
    for (let number = 2; number <= 4; number++) {
      await scroll.evaluate(element => {
        element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: -100000 }))
        element.scrollTop = 0
      })
      await expect.poll(() => reads).toBe(number)
      const oldestBefore = page.locator(`[data-message-id="message-${200 - (number - 1) * 50}"]`)
      await expect(oldestBefore).toBeInViewport()
      await expect.poll(() => scroll.evaluate(element => element.scrollTop)).toBeGreaterThan(100)
    }
    expect(await page.locator('.message-row').count()).toBeLessThan(100)
    const history = page.getByRole('region', { name: 'Message history', exact: true })
    await history.focus()
    await history.press('Home')
    await expect(page.locator('[data-message-id="message-0"]')).toBeInViewport()
    await history.press('End')
    await expect(last).toBeInViewport()
    await expect.poll(() => scroll.evaluate(element => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThan(5)
    await page.screenshot({ path: testInfo.outputPath('long-history.png') })
    await page.evaluate(() => window.testApp.unmount())
    await open()
    await expect(last).toBeInViewport()
    expect(reads).toBe(5)
  })
}

test('Markdown survives virtual unmount without another download and is invalidated in another room', async ({ page }) => {
  let reads = 0
  await page.route('**/api/chat/rooms/*/files/notes*', route => {
    reads++
    return route.fulfill({ contentType: 'text/markdown', body: `# Notes ${reads}` })
  })
  const items = messages(400)
  items[0].files = [{ id: 'notes', name: 'notes.md', mime_type: 'text/markdown', kind: 'file' }]
  await timeline(page, items)
  await expect(page.getByRole('heading', { name: 'Notes 1', exact: true })).toBeVisible()
  await scrollTo(page, 'end')
  await expect(page.locator('[data-message-id="message-0"]')).toHaveCount(0)
  await scrollTo(page, 'start')
  await expect(page.getByRole('heading', { name: 'Notes 1', exact: true })).toBeVisible()
  expect(reads).toBe(1)
  await page.evaluate(() => window.testApp.setProps({ roomId: 'another-room' }))
  await expect(page.getByRole('heading', { name: 'Notes 2', exact: true })).toBeVisible()
  expect(reads).toBe(2)
})

test('playing audio stays mounted outside the window and can be released after pausing', async ({ page }) => {
  const samples = 8000 * 30
  const wav = Buffer.alloc(44 + samples * 2)
  wav.write('RIFF', 0); wav.writeUInt32LE(36 + samples * 2, 4); wav.write('WAVEfmt ', 8)
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28)
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34)
  wav.write('data', 36); wav.writeUInt32LE(samples * 2, 40)
  await page.route('**/api/chat/rooms/*/files/audio*', route => route.fulfill({ contentType: 'audio/wav', body: wav }))
  const items = messages(400)
  items[0].files = [{ id: 'audio', name: 'audio.wav', mime_type: 'audio/wav', kind: 'audio' }]
  await timeline(page, items)
  const audio = page.locator('audio')
  await expect(audio).toBeVisible()
  await audio.evaluate(async element => {
    element.muted = true
    element.dataset.playbackToken = 'retained'
    await element.play()
  })
  await scrollTo(page, 'end')
  await expect(page.locator('[data-message-id="message-399"]')).toBeInViewport()
  await expect(audio).toHaveAttribute('data-playback-token', 'retained')
  expect(await audio.evaluate(element => element.paused)).toBe(false)
  await audio.evaluate(element => element.pause())
  await expect(page.locator('[data-message-id="message-0"]')).toHaveCount(0)
})
