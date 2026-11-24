import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP8/x8AAwMCAHwG0LwAAAAASUVORK5CYII=', 'base64')
const harness = 'test-support/browser/AgentAvatarHarness.vue'

test('both authorized avatar endpoints reuse their own portraits after a full page reload', async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem('galaris:session-generation')) {
      localStorage.setItem('access_token', 'component-test')
      localStorage.setItem('galaris:session-generation', 'avatar-reload-test')
    }
  })
  let removed = false
  let management = 0, chat = 0
  await page.route(/\/api\/agents\/7\/avatar(?:\?.*)?$/, route => {
    if (route.request().method() === 'DELETE') {
      removed = true
      return route.fulfill({ status: 204 })
    }
    management++
    return removed ? route.fulfill({ status: 404 }) : route.fulfill({ contentType: 'image/png', body: png })
  })
  await page.route('**/api/chat/agents/7/avatar', route => {
    chat++
    return removed ? route.fulfill({ status: 404 }) : route.fulfill({ contentType: 'image/png', body: png })
  })
  async function expectPortraits(expectedReads) {
    await mount(page, harness, { props: { showChat: true } })
    const portraits = page.getByRole('img', { name: 'Test Agent' })
    await expect(portraits).toHaveCount(3)
    await expect.poll(() => portraits.evaluateAll(images => images.map(image => image.naturalWidth))).toEqual([1, 1, 1])
    expect([management, chat]).toEqual([expectedReads, expectedReads])
  }
  await expectPortraits(1)
  await expectPortraits(1)

  await page.evaluate(() => window.testApp.setProps({ showManagement: false, showChat: false }))
  await page.evaluate(async () => {
    const { clearStoredSession, saveAccessToken } = await import('/core/api.ts')
    clearStoredSession()
    saveAccessToken('second-user')
  })
  await expectPortraits(2)
  await page.evaluate(() => window.testApp.setProps({ showManagement: false, showChat: false }))
  await page.evaluate(async () => {
    const { agentService } = await import('/app/agent/services/agentService.ts')
    await agentService.deleteAvatar(7)
  })
  await mount(page, harness, { props: { showChat: true } })
  await expect.poll(() => [management, chat]).toEqual([3, 3])
  await expect(page.getByRole('img', { name: 'Test Agent' })).toHaveCount(0)
})

test('text and phone histories display and reuse portraits without the administration catalogue', async ({ page }, testInfo) => {
  const date = '2026-01-01T12:00:00Z'
  const agent = { agent_id: 7, agent_name: 'Test Agent', room_id: 'synthetic-room' }
  const rows = (row) => Array.from({ length: 8 }, (_, index) => ({ ...agent, ...row, id: `synthetic-${index}` }))
  await jsonRoute(page, '**/api/agents/selection?scope=management', [{ id: 7, label: 'Test Agent', has_avatar: true }])
  await jsonRoute(page, '**/api/conversations/messages?*', {
    items: rows({ created_at: date, channel_kind: 'telegram', payload: { text: 'Synthetic message' }, aggregated_message_count: 1 }),
    page: 1, page_size: 50, total: 8, summary: { idle: 8, ready: 0, running: 0, errors: 0 },
  })
  await jsonRoute(page, '**/api/voice/conversations?*', {
    items: rows({ started_at: date, duration: 5, transport_kind: 'sip', status: 'COMPLETED', turn_count: 0, turns: [] }),
    page: 1, page_size: 50, total: 8, summary: { active: 0, completed: 8, cancelled: 0, errors: 0 },
  })
  let reads = 0
  await page.route(/\/api\/agents\/7\/avatar(?:\?.*)?$/, route => {
    reads++
    return route.fulfill({ contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="48" height="48" fill="#2364aa"/><circle cx="24" cy="16" r="8" fill="#fff"/><ellipse cx="24" cy="41" rx="15" ry="13" fill="#fff"/></svg>',
    })
  })
  await mount(page, 'app/index/pages/task.vue', {
    route: '/task', shell: true, privileges: ['CONVERSATION_ACCESS', 'VOICE_HISTORY_ACCESS'],
  })
  for (const [history, tab] of [['text', 'Text conversations'], ['phone', 'Phone calls'], ['reopened', 'Text conversations']]) {
    const currentTab = page.getByRole('tab', { name: tab })
    await currentTab.click()
    await expect(currentTab).toHaveAttribute('aria-selected', 'true')
    const searchLabel = history === 'phone' ? 'Search rooms and transcripts' : 'Search a message, conversation, or participant'
    await expect(page.getByRole('textbox', { name: searchLabel, exact: true })).toBeVisible()
    for (const [width, dark] of [[1440, false], [390, true]]) {
      await page.setViewportSize({ width, height: 900 })
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      const rows = width < 1024
        ? page.locator(history === 'phone' ? '.voice-mobile-card' : '.conversation-mobile-card')
        : page.getByRole('table')
      const portraits = rows.getByRole('img', { name: 'Test Agent' })
      await expect(portraits).toHaveCount(8)
      await expect.poll(() => portraits.evaluateAll(images => images.map(image => image.naturalWidth))).toEqual(Array(8).fill(48))
      await portraits.first().scrollIntoViewIfNeeded()
      await page.screenshot({ path: testInfo.outputPath(`${history}-${width}.png`) })
    }
    expect(reads).toBe(1)
  }
})

test('owner and activity avatars share missing results and see a newly uploaded portrait', async ({ page }) => {
  let uploaded = false, reads = 0
  await page.route(/\/api\/agents\/7\/avatar(?:\?.*)?$/, route => {
    if (route.request().method() === 'POST') { uploaded = true; return route.fulfill({ status: 204 }) }
    reads++
    return uploaded ? route.fulfill({ contentType: 'image/png', body: png }) : route.fulfill({ status: 404 })
  })
  await mount(page, harness)
  await expect.poll(() => reads).toBe(1)
  await expect(page.locator('.management-avatars')).toHaveText('TATA')
  await page.evaluate(() => window.testApp.mount({
    component: 'app/share/components/OwnerAvatar.vue',
    props: { owner: { kind: 'agent', id: 7, label: 'Test Agent' } },
  }))
  await expect(page.locator('.user-avatar')).toHaveText('TA')
  await page.evaluate(async () => {
    const { agentService } = await import('/app/agent/services/agentService.ts')
    await agentService.uploadAvatar(7, new File(['synthetic'], 'avatar.png', { type: 'image/png' }))
  })
  await expect(page.getByRole('img', { name: 'Test Agent' })).toHaveJSProperty('naturalWidth', 1)
  await page.evaluate(component => window.testApp.mount({ component }), harness)
  await expect(page.getByRole('img', { name: 'Test Agent' })).toHaveCount(2)
  expect(reads).toBe(2)
})

test('management avatars reuse cached bytes across mounts while each consumer owns its image URL', async ({ page }) => {
  await page.clock.install()
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
  // Catalogue refreshes must invalidate a portrait even while has_avatar stays true.
  const cached = await images.first().getAttribute('src')
  await page.evaluate(async () => {
    const { useAgentStore } = await import('/app/agent/stores/agentStore.ts')
    useAgentStore(window.testApp.pinia).agents = [{
      id: 7, first_name: 'Test', last_name: 'Agent', has_avatar: true,
      updated_at: '2026-01-01T12:00:00Z',
    }]
  })
  await expect.poll(() => reads).toBe(2)
  await expect(images.first()).toHaveJSProperty('naturalWidth', 1)
  await expect(images.first()).not.toHaveAttribute('src', cached)
  await page.clock.fastForward(120_000)
  await page.evaluate(() => window.testApp.setProps({ showManagement: false }))
  await expect(images).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ showManagement: true }))
  await expect(images).toHaveCount(2)
  await expect(images.first()).toHaveJSProperty('naturalWidth', 1)
  expect(reads).toBe(2)
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
  let managementReads = 0
  await page.route('**/api/chat/agents/7/avatar', route => removed ? route.fulfill({ status: 404 }) : route.fulfill({ contentType: 'image/png', body: png }))
  await page.route(/\/api\/agents\/7\/avatar(?:\?.*)?$/, route => {
    if (route.request().method() === 'DELETE') { removed = true; return route.fulfill({ status: 204 }) }
    managementReads++
    return route.fulfill({ status: 403 })
  })
  await mount(page, harness, { props: { showManagement: false, showChat: true } })
  await expect(page.locator('.chat-avatar img')).toHaveJSProperty('naturalWidth', 1)
  await page.evaluate(() => window.testApp.setProps({ showManagement: true }))
  await expect.poll(() => managementReads).toBe(1)
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
    return route.fulfill({ json: [
      { id: 7, label: 'Émile Exemple', has_avatar: false },
      { id: 8, label: 'Zoé Exemple', has_avatar: false },
    ] })
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
    return { labels: [second[0].label, teams[0].label], ids: second.map(agent => agent.id), cancelled: await cancelled }
  })
  expect(result).toEqual({ labels: ['Émile Exemple', 'Émile Exemple'], ids: [7, 8], cancelled: 'AbortError' })
  expect(reads.sort()).toEqual(['management', 'management', 'teams'])
})
