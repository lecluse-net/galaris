import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const room = { id: 'synthetic-room', agent_id: 7, agent_name: 'Synthetic agent', label: 'Synthetic discussion',
  external_id: 'synthetic', kind: 'chat', conversation_type: 'text', members: [] }
const message = number => ({ id: `message-${number}`, external_id: String(number), room_id: room.id,
  text: `Synthetic message ${number}\nA paragraph retained while reading the discussion.`,
  sender: { display_name: 'Synthetic participant' }, is_mine: false, files: [],
  created_at: new Date(Date.UTC(2026, 8, 1, 12, number)).toISOString() })

async function openDiscussion(page, width = 1440) {
  await page.setViewportSize({ width, height: 900 })
  await jsonRoute(page, '**/api/chat/rooms/synthetic-room', room)
  await jsonRoute(page, '**/api/chat/rooms/synthetic-room/speech/status', { available_agent_ids: [] })
  await jsonRoute(page, '**/api/chat/rooms/synthetic-room/messages/*/previews?*', [])
  await mount(page, 'resourceDetails.vue', {
    props: { target: { kind: 'room', id: room.id, title: room.label } },
  })
  await expect(page.getByRole('dialog').getByText('Synthetic message 100', { exact: false })).toBeVisible()
}

for (const width of [1440, 390]) test(`discussion opens at the latest message and scrolls history both ways at ${width}px`, async ({ page }, testInfo) => {
  let latestReads = 0, olderReads = 0, newest = 100
  let releaseHistory
  const pendingHistory = new Promise(resolve => { releaseHistory = resolve })
  await page.route('**/api/chat/rooms/synthetic-room/messages?*', async route => {
    const params = new URL(route.request().url()).searchParams
    const pageNumber = Number(params.get('page'))
    if (pageNumber > 1) {
      olderReads++
      expect(params.get('history_cursor')).toBe('synthetic-cursor')
      await pendingHistory
    } else latestReads++
    const numbers = pageNumber === 1 ? Array.from({ length: 50 }, (_, n) => newest - n)
      : Array.from({ length: 50 }, (_, n) => 50 - n)
    await route.fulfill({ json: { items: numbers.map(message), page: pageNumber, total: 100,
      provider_history: true, history_has_more: pageNumber === 1, history_next_cursor: pageNumber === 1 ? 'synthetic-cursor' : null } })
  })
  await openDiscussion(page, width)
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('button', { name: 'Load earlier messages', exact: true })).toHaveCount(0)
  const scroll = dialog.locator('.q-scrollarea__container')
  await expect.poll(() => scroll.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(5)
  expect(latestReads).toBe(1)
  expect(olderReads).toBe(0)
  await scroll.hover()
  await page.mouse.wheel(0, -100000)
  await expect.poll(() => olderReads).toBe(1)
  const anchor = dialog.locator('[data-message-id="message-51"]')
  await expect(anchor).toBeInViewport()
  const top = (await anchor.boundingBox()).y
  await page.mouse.wheel(0, -100000)
  expect(olderReads).toBe(1)
  releaseHistory()
  await expect(dialog.locator('[data-message-id="message-1"]')).toBeAttached()
  await expect.poll(async () => Math.abs((await anchor.boundingBox()).y - top)).toBeLessThan(5)
  await expect(dialog.getByRole('button', { name: 'Go to the latest message', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('discussion-history.png') })

  newest = 101
  await dialog.getByRole('button', { name: 'Go to the latest message', exact: true }).click()
  await expect(dialog.getByText('Synthetic message 101', { exact: false })).toBeVisible()
  await expect.poll(() => scroll.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(5)
  await expect(dialog.getByRole('button', { name: 'Go to the latest message', exact: true })).toHaveCount(0)
  expect(latestReads).toBe(2)
  await page.clock.setFixedTime(new Date(await page.evaluate(() => Date.now()) + 2000))
  newest = 102
  await scroll.hover()
  await page.mouse.wheel(0, -500)
  await expect(dialog.getByRole('button', { name: 'Go to the latest message', exact: true })).toBeVisible()
  await page.mouse.wheel(0, 100000)
  await expect(dialog.getByText('Synthetic message 102', { exact: false })).toBeVisible()
  await expect.poll(() => scroll.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(5)
  expect(latestReads).toBe(3)
  await scroll.focus()
  await expect(scroll).toBeFocused()
  await page.keyboard.press('Home')
  await expect(dialog.locator('[data-message-id="message-1"]')).toBeInViewport()
  await expect(dialog.getByRole('button', { name: 'Go to the latest message', exact: true })).toBeVisible()
  await page.keyboard.press('End')
  await expect.poll(() => scroll.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(5)
  await expect(dialog.getByRole('button', { name: 'Go to the latest message', exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await page.evaluate(() => window.testApp.unmount())
  await openDiscussion(page, width)
  await expect.poll(() => page.locator('.q-scrollarea__container').evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(5)
})

test('jumping to the latest messages while history loads schedules one fresh read', async ({ page }) => {
  let latestReads = 0, olderReads = 0, releaseHistory
  const pendingHistory = new Promise(resolve => { releaseHistory = resolve })
  await page.route('**/api/chat/rooms/synthetic-room/messages?*', async route => {
    const pageNumber = Number(new URL(route.request().url()).searchParams.get('page'))
    if (pageNumber > 1) { olderReads++; await pendingHistory }
    else latestReads++
    const newest = pageNumber === 1 ? latestReads > 1 ? 101 : 100 : 50
    await route.fulfill({ json: { items: Array.from({ length: 50 }, (_, n) => message(newest - n)),
      total: 100, page: pageNumber, provider_history: false, history_has_more: false, history_next_cursor: null } })
  })
  await openDiscussion(page)
  const dialog = page.getByRole('dialog')
  const scroll = dialog.locator('.q-scrollarea__container')
  await expect.poll(() => scroll.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(5)
  await scroll.hover()
  await page.mouse.wheel(0, -100000)
  await expect.poll(() => olderReads).toBe(1)
  await dialog.getByRole('button', { name: 'Go to the latest message', exact: true }).click()
  releaseHistory()
  await expect(dialog.getByText('Synthetic message 101', { exact: false })).toBeVisible()
  await expect.poll(() => scroll.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(5)
  expect(latestReads).toBe(2)
})

test('history errors retain the discussion and late pages cannot replace another room', async ({ page }) => {
  let olderReads = 0, releaseHistory
  const pendingHistory = new Promise(resolve => { releaseHistory = resolve })
  await page.route('**/api/chat/rooms/synthetic-room/messages?*', async route => {
    const pageNumber = Number(new URL(route.request().url()).searchParams.get('page'))
    if (pageNumber > 1) {
      if (++olderReads === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic history unavailable' } })
      await pendingHistory
    }
    await route.fulfill({ json: { items: Array.from({ length: 50 }, (_, n) => message((pageNumber === 1 ? 100 : 50) - n)),
      total: 100, page: pageNumber, provider_history: false, history_has_more: false, history_next_cursor: null } })
  })
  await openDiscussion(page)
  const dialog = page.getByRole('dialog')
  const scroll = dialog.locator('.q-scrollarea__container')
  await expect.poll(() => scroll.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(5)
  await scroll.hover()
  await page.mouse.wheel(0, -100000)
  await expect(dialog.getByText('The Messenger operation failed.', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Synthetic message 51', { exact: false })).toBeVisible()
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(() => olderReads).toBe(2)
  const other = { ...room, id: 'other-room', label: 'Other synthetic discussion' }
  await jsonRoute(page, '**/api/chat/rooms/other-room', other)
  await jsonRoute(page, '**/api/chat/rooms/other-room/speech/status', { available_agent_ids: [] })
  await jsonRoute(page, '**/api/chat/rooms/other-room/messages?*', {
    items: [], total: 0, page: 1, provider_history: false, history_has_more: false, history_next_cursor: null,
  })
  await page.evaluate(target => window.testApp.setProps({ target }), { kind: 'room', id: other.id, title: other.label })
  await expect(dialog.getByText('No messages', { exact: true })).toBeVisible()
  const response = page.waitForResponse(url => url.url().includes('/synthetic-room/messages?') && url.status() === 200)
  releaseHistory()
  await response
  await expect(dialog.getByText('No messages', { exact: true })).toBeVisible()
  await expect(dialog.locator('[data-message-id]')).toHaveCount(0)
})
