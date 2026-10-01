import { test, expect, mount } from './fixtures.mjs'

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5AAAAABJRU5ErkJggg==', 'base64')
const harness = 'test-support/browser/AgentAvatarHarness.vue'

test('management avatars reuse cached bytes across mounts while each consumer owns its image URL', async ({ page }) => {
  let reads = 0
  await page.route(/\/api\/agents\/7\/avatar(?:\?.*)?$/, route => { reads++; return route.fulfill({ contentType: 'image/png', body: png }) })
  await mount(page, harness)
  const images = page.locator('.management-avatars img')
  await expect(images).toHaveCount(2)
  await expect(images.first()).toHaveJSProperty('naturalWidth', 1)
  expect(reads).toBe(1)
  const previous = await images.first().getAttribute('src')
  await page.evaluate(() => window.testApp.setProps({ showManagement: false }))
  await expect(images).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ showManagement: true }))
  await expect(images).toHaveCount(2)
  await expect(images.first()).toHaveJSProperty('naturalWidth', 1)
  expect(reads).toBe(1)
  await expect(images.first()).not.toHaveAttribute('src', previous)
  expect(await page.evaluate(async () => {
    const { agentService } = await import('/app/agent/services/agentService.ts')
    const [first, second] = await Promise.all([agentService.getAvatarBlobUrl(7), agentService.getAvatarBlobUrl(7)])
    URL.revokeObjectURL(first)
    const valid = (await fetch(second)).ok
    URL.revokeObjectURL(second)
    return valid && first !== second
  })).toBe(true)
  expect(reads).toBe(1)
})

test('successful avatar replacement invalidates both authorized endpoints and logout clears mounted images', async ({ page }) => {
  let management = 0, chat = 0
  await page.route(/\/api\/agents\/7\/avatar(?:\?.*)?$/, route => {
    if (route.request().method() === 'POST') return route.fulfill({ status: 204 })
    management++
    return route.fulfill({ contentType: 'image/png', body: png })
  })
  await page.route('**/api/chat/agents/7/avatar', route => { chat++; return route.fulfill({ contentType: 'image/png', body: png }) })
  await mount(page, harness, { props: { showChat: true } })
  await expect(page.locator('img')).toHaveCount(3)
  const first = await page.locator('.management-avatars img').first().getAttribute('src')
  await page.evaluate(async () => {
    const { agentService } = await import('/app/agent/services/agentService.ts')
    await agentService.uploadAvatar(7, new File(['synthetic'], 'avatar.png', { type: 'image/png' }))
  })
  await expect.poll(() => [management, chat]).toEqual([2, 2])
  await expect(page.locator('img')).toHaveCount(3)
  await expect(page.locator('.management-avatars img').first()).not.toHaveAttribute('src', first)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: null })))
  await expect(page.locator('img')).toHaveCount(0)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('galaris:auth-token-changed', { detail: 'new-session' })))
  await expect(page.locator('img')).toHaveCount(3)
  expect([management, chat]).toEqual([3, 3])
})

test('chat access cannot populate the management cache and removing an avatar clears existing consumers', async ({ page }) => {
  let removed = false
  await page.route('**/api/chat/agents/7/avatar', route => removed ? route.fulfill({ status: 404 }) : route.fulfill({ contentType: 'image/png', body: png }))
  await page.route('**/api/agents/7/avatar', route => {
    if (route.request().method() === 'DELETE') { removed = true; return route.fulfill({ status: 204 }) }
    return route.fulfill({ status: 403 })
  })
  await mount(page, harness, { props: { showManagement: false, showChat: true } })
  await expect(page.locator('.chat-avatar img')).toHaveJSProperty('naturalWidth', 1)
  await page.evaluate(() => window.testApp.setProps({ showManagement: true }))
  await expect(page.locator('.management-avatars')).toHaveText('TATA')
  await page.evaluate(async () => {
    const { agentService } = await import('/app/agent/services/agentService.ts')
    await agentService.deleteAvatar(7)
  })
  await expect(page.locator('img')).toHaveCount(0)
})

test('agent selectors share reads by scope, survive one cancelled reader and return independent copies', async ({ page }) => {
  const reads = []
  await page.route('**/api/agents/selection?scope=*', route => {
    reads.push(new URL(route.request().url()).searchParams.get('scope'))
    return route.fulfill({ json: [{ id: 7, label: 'Test Agent', has_avatar: false }] })
  })
  await mount(page, harness, { props: { showManagement: false } })
  reads.length = 0
  const result = await page.evaluate(async () => {
    const { getAgentSelection } = await import('/app/agent/services/agentSelectionService.ts')
    const controller = new AbortController()
    const cancelled = getAgentSelection('management', controller.signal)
      .then(() => 'unexpected success', error => error.name)
    const selections = Promise.all([
      getAgentSelection('management'), getAgentSelection('management'), getAgentSelection('teams'),
    ])
    controller.abort()
    const [first, second, teams] = await selections
    first[0].label = 'Locally edited'
    await getAgentSelection('management')
    return { labels: [second[0].label, teams[0].label], cancelled: await cancelled }
  })
  expect(result).toEqual({ labels: ['Test Agent', 'Test Agent'], cancelled: 'AbortError' })
  expect(reads.sort()).toEqual(['management', 'management', 'teams'])
})
