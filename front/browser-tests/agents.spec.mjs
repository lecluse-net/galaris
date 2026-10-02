import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent } from './data.mjs'

async function agentFixtures(page) {
  await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'hermes', is_owner: true }])
  await jsonRoute(page, '**/api/agents/titles?*', [])
  await jsonRoute(page, '**/api/agents/groups?*', [])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'hermes', label: 'Hermes', manages_runtime: true }])
  await jsonRoute(page, '**/api/harnesses/agents/7', { containerized: true })
}

test('reopening agent management refreshes catalogues and reloading retrieves them again', async ({ page }) => {
  await agentFixtures(page)
  const reads = { agents: 0, titles: 0, groups: 0 }
  for (const [key, url] of Object.entries({ agents: '**/api/agents?*', titles: '**/api/agents/titles?*', groups: '**/api/agents/groups?*' })) {
    await page.route(url, route => { reads[key]++; return route.fulfill({ json: [] }) })
  }
  const options = { component: 'app/agent/pages/index.vue', privileges: ['AGENT_EDIT'] }
  await mount(page, options.component, options)
  await expect(page.getByRole('button', { name: 'New Agent', exact: true })).toBeVisible()
  await expect.poll(() => reads).toEqual({ agents: 1, titles: 1, groups: 1 })
  await page.evaluate(async options => {
    window.testApp.unmount()
    await window.testApp.mount(options)
  }, options)
  await expect(page.getByRole('button', { name: 'New Agent', exact: true })).toBeVisible()
  // A new management visit refreshes grants and shared reference data, including empty lists.
  await page.evaluate(async () => {
    const { useAgentStore } = await import('/app/agent/stores/agentStore.ts')
    const store = useAgentStore(window.testApp.pinia)
    await Promise.all([store.fetchAgents(), store.fetchTitles(), store.fetchGroups()])
  })
  expect(reads).toEqual({ agents: 2, titles: 2, groups: 2 })
  await mount(page, options.component, options) // Full navigation, equivalent to F5 for memory caches.
  await expect.poll(() => reads).toEqual({ agents: 3, titles: 3, groups: 3 })
})

test('agent creation requires a first name but accepts an empty last name', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  const titles = Array.from({ length: 500 }, (_, index) => ({ id: index + 1, label: `Synthetic title ${index + 1}`, gender: 'X' }))
  titles.push({ id: 501, label: 'agent_titles.ms', gender: 'F' })
  await page.route('**/api/agents/titles?*', route => {
    const skip = Number(new URL(route.request().url()).searchParams.get('skip') ?? 0)
    return route.fulfill({ json: titles.slice(skip, skip + 500) })
  })
  const saves = []
  await page.route('**/api/agents', route => {
    const data = route.request().postDataJSON()
    saves.push(data)
    if (data.code === 'lyra') {
      return route.fulfill({ status: 400, json: { detail: 'This code is already used by another agent. Please choose a different code.' } })
    }
    return route.fulfill({ status: 201, json: { ...agent, ...data } })
  })
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
  await page.getByRole('button', { name: 'New Agent', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Agent code', { exact: true }).fill('lyra')
  await dialog.getByLabel('Title *', { exact: true }).click()
  await expect(page.getByRole('option').first()).toBeVisible()
  await page.keyboard.press('End')
  await page.getByRole('option', { name: 'Ms (F)', exact: true }).click()
  await dialog.getByLabel('First name *', { exact: true }).fill('   ')
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(dialog.getByText('First name is required', { exact: true })).toBeVisible()
  expect(saves).toEqual([])
  await dialog.getByLabel('First name *', { exact: true }).fill('Lyra')
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByText('This code is already used by another agent. Please choose a different code.', { exact: true })).toBeVisible()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue('Lyra')
  await dialog.getByLabel('Agent code', { exact: true }).fill('lyra-available')
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(saves).toHaveLength(2)
  expect(saves[1]).toMatchObject({ code: 'lyra-available', first_name: 'Lyra', last_name: '', title_id: 501 })
})

test('a refreshed portrait survives an older catalogue avatar response', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/harnesses/agents/*/status', { status: 'stopped', managed: false, containerized: false, capabilities: [], available_actions: [] })
  const target = { ...agent, id: 8, code: 'synthetic-portrait', first_name: 'Lyra', last_name: 'Synthetic', agent_driver: 'internal', is_owner: true }
  let catalogue = [{ ...agent, agent_driver: 'internal', has_avatar: true, avatar_revision: 1 }, { ...target, has_avatar: false, avatar_revision: 0 }]
  await page.route('**/api/agents?*', route => route.fulfill({ json: catalogue }))
  const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5AAAAABJRU5ErkJggg==', 'base64')
  let release, started = false
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/agents/7/avatar?*', async route => {
    started = true
    await pending
    await route.fulfill({ contentType: 'image/png', body: image })
  })
  await page.route('**/api/agents/8/avatar?*', route => route.fulfill({ contentType: 'image/png', body: image }))
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
  await expect.poll(() => started).toBe(true)
  // Observe disposal at the browser resource boundary, without mocking the loader.
  await page.evaluate(() => {
    window.disposedPortraits = 0
    const revoke = URL.revokeObjectURL.bind(URL)
    URL.revokeObjectURL = url => { window.disposedPortraits++; revoke(url) }
  })
  try {
    catalogue = [{ ...catalogue[0], has_avatar: false, avatar_revision: 2 }, { ...target, has_avatar: true, avatar_revision: 1 }]
    await page.evaluate(async () => {
      const { invalidateSessionReads } = await import('/core/util/sessionReadCache.ts')
      const { useAgentStore } = await import('/app/agent/stores/agentStore.ts')
      invalidateSessionReads('agent-catalogue')
      await useAgentStore(window.testApp.pinia).fetchAgents()
    })
    const portrait = page.getByRole('img', { name: 'Lyra Synthetic', exact: true })
    await expect(portrait).toBeVisible()
    await expect(portrait).toHaveJSProperty('naturalWidth', 1)
    release()
    await expect.poll(() => page.evaluate(() => window.disposedPortraits)).toBeGreaterThan(0)
    await expect(portrait).toBeVisible()
    await expect(portrait).toHaveJSProperty('naturalWidth', 1)
  } finally { release() }
})

test('built-in titles follow the locale and remain keys until renamed', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/harnesses/agents/7/status', { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: [], available_actions: [], last_error: null })
  await jsonRoute(page, '**/api/agents/titles?*', [
    { id: 1, label: 'agent_titles.ms', gender: 'F' },
    { id: 2, label: 'agent_titles.mr', gender: 'M' },
    { id: 3, label: 'common.save', gender: 'M' },
  ])
  const saves = []
  await page.route('**/api/agents/titles/1', route => {
    const data = route.request().postDataJSON()
    saves.push(data)
    return route.fulfill({ json: { id: 1, ...data } })
  })
  const locale = language => page.evaluate(async language => {
    const { setLocale } = await import('/core/i18n/index.ts')
    setLocale(language)
  }, language)
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT', 'AGENT_MANAGE_ALL'] })
  await page.getByRole('tab', { name: 'Titles' }).click()
  await expect(page.getByRole('cell', { name: 'Ms', exact: true })).toBeVisible()
  await locale('fr')
  await expect(page.getByRole('cell', { name: 'Madame', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Monsieur', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'common.save', exact: true })).toBeVisible()
  await page.getByRole('row').filter({ has: page.getByRole('cell', { name: 'Madame', exact: true }) }).getByRole('button').first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('textbox')).toHaveValue('Madame')
  await locale('en')
  await expect(dialog.getByRole('textbox')).toHaveValue('Ms')
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(saves).toEqual([{ label: 'agent_titles.ms', gender: 'F' }])
  await page.getByRole('row').filter({ has: page.getByRole('cell', { name: 'Ms', exact: true }) }).getByRole('button').first().click()
  await expect(dialog.getByRole('textbox')).toHaveValue('Ms')
  await dialog.getByRole('textbox').fill('Doctor')
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(saves.at(-1)).toEqual({ label: 'Doctor', gender: 'F' })
  await locale('zh')
  await expect(page.getByRole('cell', { name: 'Doctor', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '先生', exact: true })).toBeVisible()
  await expect(page.getByText('agent_titles.', { exact: false })).toHaveCount(0)
})

test('internal agents remain editable without external runtime supervision', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'internal', is_owner: true }])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  let supervisionReads = 0
  await page.route('**/api/harnesses/agents/7/status', route => {
    supervisionReads++
    return route.fulfill({ status: 503, json: { detail: 'External manager unavailable' } })
  })
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
  await expect(page.getByText('Alice Example', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'New Agent', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  expect(supervisionReads).toBe(0)
  await expect(page.locator('.q-banner').filter({ hasText: /manager/i })).toHaveCount(0)
})

for (const [driver, driverMetadata] of [['hermes', true], ['hermes', false], ['openai_messages', true]]) {
  test(`agent page reports an unavailable manager and recovers for ${driver} with metadata ${driverMetadata}`, async ({ page }) => {
    await page.clock.install()
    await agentFixtures(page)
    if (driver === 'openai_messages') {
      await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: driver, is_owner: true }])
      await jsonRoute(page, '**/api/agents/drivers', [{ name: driver, manages_runtime: false }])
    }
    if (!driverMetadata) await jsonRoute(page, '**/api/agents/drivers', [])
    await jsonRoute(page, '**/api/harnesses/agents/7/selection', { containerized: true })
    let healthy = false
    await page.route('**/api/harnesses/agents/7/status', route => route.fulfill(healthy
      ? { json: { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: ['restart', 'stop'], available_actions: ['restart', 'stop'], last_error: null } }
      : { status: 503, json: { detail: 'Manager unavailable' } }))
    await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
    const warning = page.locator('.q-banner').filter({ hasText: /manager/i })
    await expect(warning).toBeVisible()
    healthy = true
    await page.clock.fastForward(5100)
    await expect(warning).toHaveCount(0)
    await expect(page.getByText('Alice Example', { exact: true }).first()).toBeVisible()
  })
}

test('agent runtime action calls restart once and prevents duplicate submissions', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/harnesses/agents/7/status', { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: ['restart', 'stop'], available_actions: ['restart', 'stop'], last_error: null })
  let release
  const pending = new Promise(resolve => { release = resolve })
  const actions = []
  await page.route('**/api/harnesses/agents/7/actions/restart', async route => {
    actions.push(route.request().method())
    await pending
    await route.fulfill({ json: { status: 'queued', output: '' } })
  })
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
  const restart = page.getByRole('button', { name: 'Restart', exact: true })
  try {
    await restart.click()
    await expect.poll(() => actions).toEqual(['POST'])
    await restart.click({ force: true })
    expect(actions).toEqual(['POST'])
  } finally { release() }
})
