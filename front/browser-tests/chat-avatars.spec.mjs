import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5AAAAABJRU5ErkJggg==', 'base64')
const messages = count => Array.from({ length: count }, (_, index) => ({
  id: `message-${index}`, external_id: `message-${index}`, text: `Reply ${index}`, files: [],
  sender: { agent_id: 7, display_name: 'Test Agent', is_ai: true },
  created_at: '2026-09-01T12:00:00Z', is_mine: false,
}))

async function timeline(page, count = 50) {
  await jsonRoute(page, '**/api/chat/rooms/room/speech/status*', { available_agent_ids: [] })
  await mount(page, 'app/chat/components/MessageTimeline.vue', {
    props: { roomId: 'room', agentId: 7, agentName: 'Test Agent', messages: messages(count), activity: [], liveRound: null },
  })
}

for (const status of [200, 404]) test(`fifty bubbles share one avatar request (${status}) and keep messages usable`, async ({ page }) => {
  let requests = 0
  await page.route('**/api/chat/agents/7/avatar', route => {
    requests++
    return route.fulfill({ status, contentType: 'image/png', body: status === 200 ? png : '' })
  })
  await timeline(page)
  await expect(page.locator('.message-text').first()).toContainText('Reply 0')
  if (status === 200) await expect(page.locator('.internal-agent-avatar img')).toHaveCount(50)
  else await expect(page.locator('.internal-agent-avatar').first()).toHaveText('TA')
  await page.waitForTimeout(400)
  expect(requests).toBe(1)
  await page.evaluate(messages => window.testApp.setProps({ messages }), messages(1))
  if (status === 200) await expect(page.locator('.internal-agent-avatar img')).toHaveJSProperty('naturalWidth', 1)
  expect(requests).toBe(1)
})

test('the remaining bubble keeps a shared request alive and reopening retries failures', async ({ page }) => {
  let requests = 0, release
  await page.route('**/api/chat/agents/7/avatar', async route => {
    requests++
    if (requests === 1) await new Promise(resolve => { release = resolve })
    return route.fulfill({ status: requests === 1 ? 503 : 200, contentType: 'image/png', body: png })
  })
  await timeline(page)
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.evaluate(messages => window.testApp.setProps({ messages }), messages(1))
  await expect(page.locator('.internal-agent-avatar')).toHaveCount(1)
  release()
  await page.waitForTimeout(200)
  expect(requests).toBe(1)
  await expect(page.locator('.internal-agent-avatar')).toHaveText('TA')
  await page.evaluate(() => window.testApp.setProps({ messages: [] }))
  await expect(page.locator('.internal-agent-avatar')).toHaveCount(0)
  await page.evaluate(messages => window.testApp.setProps({ messages }), messages(1))
  await expect(page.locator('.internal-agent-avatar img')).toHaveJSProperty('naturalWidth', 1)
  expect(requests).toBe(2)
})

test('new bubbles reuse a fresh avatar and revalidate after expiration without blanking current bubbles', async ({ page }) => {
  let requests = 0, release
  await page.route('**/api/chat/agents/7/avatar', async route => {
    if (++requests === 2) await new Promise(resolve => { release = resolve })
    await route.fulfill({ contentType: 'image/png', body: png })
  })
  await timeline(page, 1)
  const first = page.locator('.internal-agent-avatar img').first()
  await expect(first).toHaveJSProperty('naturalWidth', 1)
  const previous = await first.getAttribute('src')
  await page.evaluate(messages => window.testApp.setProps({ messages }), messages(10))
  await expect(page.locator('.internal-agent-avatar img')).toHaveCount(10)
  await page.waitForTimeout(200)
  expect(requests).toBe(1)
  await expect(first).toHaveAttribute('src', previous)
  await page.evaluate(() => { const now = Date.now; Date.now = () => now() + 61_000 })
  await page.evaluate(messages => window.testApp.setProps({ messages }), messages(20))
  await expect.poll(() => Boolean(release)).toBe(true)
  await expect(page.locator('.internal-agent-avatar img')).toHaveCount(20)
  await expect(first).toHaveAttribute('src', previous)
  release()
  await expect(first).not.toHaveAttribute('src', previous)
  expect(requests).toBe(2)
})

test('session changes discard pending avatars, share the fresh image and clear on logout', async ({ page }) => {
  let requests = 0, release
  await page.route('**/api/chat/agents/7/avatar', async route => {
    requests++
    if (requests === 1) await new Promise(resolve => { release = resolve })
    return route.fulfill({ contentType: 'image/png', body: png })
  })
  await timeline(page, 3)
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.evaluate(async () => {
    const { saveAccessToken } = await import('/core/api.ts')
    saveAccessToken('new-session')
  })
  await expect(page.locator('.internal-agent-avatar img')).toHaveCount(3)
  expect(requests).toBe(2)
  const current = await page.locator('.internal-agent-avatar img').first().getAttribute('src')
  release()
  await page.waitForTimeout(200)
  await expect(page.locator('.internal-agent-avatar img').first()).toHaveAttribute('src', current)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: null })))
  await expect(page.locator('.internal-agent-avatar img')).toHaveCount(0)
  await expect(page.locator('.internal-agent-avatar').first()).toHaveText('TA')
})

test('switching agents ignores the old response and releases the previous image', async ({ page }) => {
  let release
  await page.route('**/api/chat/agents/7/avatar', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ contentType: 'image/png', body: png })
  })
  await page.route('**/api/chat/agents/8/avatar', route => route.fulfill({ contentType: 'image/png', body: png }))
  await mount(page, 'app/chat/components/InternalAgentAvatar.vue', { props: { agentId: 7, name: 'First Agent' } })
  await expect.poll(() => Boolean(release)).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ agentId: 8, name: 'Second Agent' }))
  const image = page.locator('.internal-agent-avatar img')
  await expect(image).toHaveJSProperty('naturalWidth', 1)
  const current = await image.getAttribute('src')
  release()
  await page.waitForTimeout(200)
  await expect(image).toHaveAttribute('src', current)
  await page.evaluate(() => window.testApp.unmount())
  expect(await page.evaluate(async url => {
    try { await fetch(url); return true } catch { return false }
  }, current)).toBe(false)
})
