import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent } from './data.mjs'

async function agentFixtures(page) {
  await jsonRoute(page, '**/api/agents/avatar-generation', { available: false })
  await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'hermes', is_owner: true }])
  await jsonRoute(page, '**/api/agents/titles?*', [])
  await jsonRoute(page, '**/api/agents/groups?*', [])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'hermes', label: 'Hermes', manages_runtime: true }])
  await jsonRoute(page, '**/api/harnesses/agents/7', { containerized: true })
}

for (const width of [390, 1440]) {
  test(`avatar generation recovers from errors and keeps late results with their agent (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await agentFixtures(page)
    let available = false
    await page.route('**/api/agents/avatar-generation', route => route.fulfill({ json: { available } }))
    const first = { ...agent, agent_driver: 'internal', avatar_revision: 0 }
    const second = { ...first, id: 8, code: 'lyra', first_name: 'Lyra' }
    await page.route('**/api/agents?*', route => route.fulfill({ json: [first, second] }))
    await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
    await jsonRoute(page, '**/api/agents/managers', [agent.user])
    await jsonRoute(page, '**/api/agents/titles?*', [{ id: 1, label: 'agent_titles.ms', gender: 'F' }])
    await jsonRoute(page, '**/api/harnesses/catalog?*', [])
    await jsonRoute(page, '**/api/harnesses/agents/*', { harness_id: null })
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5AAAAABJRU5ErkJggg==', 'base64')
    await page.route('**/api/agents/7/avatar?*', route => route.fulfill({ contentType: 'image/png', body: png }))
    let calls = 0, release
    const pending = new Promise(resolve => { release = resolve })
    await page.route('**/api/agents/7/avatar/generate', async route => {
      calls++
      if (calls === 1) return route.fulfill({ status: 502, json: { detail: 'Synthetic generation failure' } })
      await pending
      first.has_avatar = true
      first.avatar_revision = 1
      return route.fulfill({ json: { avatar_revision: 1 } })
    })
    await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
    const dialog = page.getByRole('dialog')
    const close = async () => {
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(dialog).toHaveCount(0)
    }
    const edit = name => page.locator('.agent-card').filter({ has: page.getByText(name, { exact: true }) }).getByRole('button', { name: 'Edit agent', exact: true })
    const generate = dialog.getByRole('button', { name: 'Generate avatar', exact: true })
    await edit('Alice Example').click()
    await expect(generate).toHaveCount(0)
    await close()
    available = true
    await edit('Alice Example').click()
    await expect(generate).toBeEnabled()
    await dialog.getByLabel('First name *', { exact: true }).fill('Draft')
    await expect(generate).toBeDisabled()
    await dialog.getByLabel('First name *', { exact: true }).fill('Alice')
    await generate.click()
    await expect(page.getByText(/Synthetic generation failure/)).toBeVisible()
    await expect(generate).toBeEnabled()
    try {
      await generate.click()
      await expect.poll(() => calls).toBe(2)
      await expect(generate).toBeDisabled()
      await close()
      await edit('Alice Example').click()
      await expect(generate).toBeDisabled()
      if (width === 390) {
        await close()
        await edit('Lyra Example').click()
      }
      release()
      await expect(page.getByText('Avatar generated successfully', { exact: true })).toBeVisible()
      await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue(width === 390 ? 'Lyra' : 'Alice')
      if (width === 390) await expect(dialog.locator('.agent-dialog-avatar img')).toHaveCount(0)
      else await expect(dialog.locator('.agent-dialog-avatar img')).toHaveJSProperty('naturalWidth', 1)
      await close()
      await edit('Alice Example').click()
      await expect(dialog.locator('.agent-dialog-avatar img')).toHaveJSProperty('naturalWidth', 1)
      await dialog.evaluate(element => Promise.all(element.getAnimations({ subtree: true }).map(animation => animation.finished)))
      await testInfo.attach('generated-avatar', { body: await dialog.screenshot(), contentType: 'image/png' })
    } finally { release() }
  })
}

for (const [mode, width] of [['create', 1440], ['edit', 390]]) {
  test(`agent ${mode} form opens while its selectors are still loading (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await agentFixtures(page)
    await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'internal', yolo: false, authorization_version: 1 }])
    await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
    await jsonRoute(page, '**/api/agents/titles?*', [{ id: 1, label: 'agent_titles.ms', gender: 'F' }])
    const pending = []
    for (const [url, json] of [
      ['**/api/agents/managers', [agent.user]],
      ['**/api/harnesses/catalog?*', []],
      ['**/api/harnesses/agents/7', { harness_id: null }],
    ]) {
      await page.route(url, async route => {
        await new Promise(resolve => pending.push(resolve))
        await route.fulfill({ json })
      })
    }
    const writes = []
    await page.route('**/api/agents/7', route => {
      const data = route.request().postDataJSON()
      writes.push(data)
      return route.fulfill({ json: { ...agent, ...data, agent_driver: 'internal' } })
    })
    await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
    await expect(page.getByText('Alice Example', { exact: true }).first()).toBeVisible()
    try {
      const started = Date.now()
      await page.getByRole('button', { name: mode === 'create' ? 'New Agent' : 'Edit agent', exact: true }).click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await testInfo.attach('opening-latency', { body: JSON.stringify({ mode, width, milliseconds: Date.now() - started, selectorsPending: pending.length }), contentType: 'application/json' })
      await dialog.getByLabel('First name *', { exact: true }).fill('Lyra')
      await expect.poll(() => pending.length).toBe(mode === 'create' ? 1 : 3)
      pending.splice(0).forEach(resolve => resolve())
      await expect(dialog.getByLabel('Human manager *', { exact: true })).toHaveValue(/Test User/)
      await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue('Lyra')
      if (mode === 'edit') {
        await expect(dialog.getByRole('switch', { name: /YOLO mode/ })).toBeVisible()
        await testInfo.attach('agent-form', { body: await dialog.screenshot(), contentType: 'image/png' })
        await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
        await expect(dialog).toHaveCount(0)
        expect(writes).toMatchObject([{ first_name: 'Lyra', user_id: 1, title_id: 1 }])
      } else {
        await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
        await expect(dialog).toHaveCount(0)
      }
    } finally { pending.splice(0).forEach(resolve => resolve()) }
  })
}

test('reopening another agent ignores a late harness selection and retries a failed catalogue', async ({ page }) => {
  await agentFixtures(page)
  const second = { ...agent, id: 8, code: 'lyra', first_name: 'Lyra', agent_driver: 'internal' }
  await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'internal' }, second])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  let failCatalogue = false
  await page.route('**/api/harnesses/catalog?*', route => route.fulfill(failCatalogue
    ? { status: 503, json: { detail: 'Synthetic catalogue failure' } }
    : { json: [{ id: 'old', name: 'Old Harness' }, { id: 'current', name: 'Current Harness' }] }))
  let release, started = false
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/harnesses/agents/7', async route => {
    started = true
    await pending
    await route.fulfill({ json: { harness_id: 'old' } })
  })
  await jsonRoute(page, '**/api/harnesses/agents/8', { harness_id: 'current' })
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT'] })
  const dialog = page.getByRole('dialog')
  const edit = name => page.locator('.agent-card').filter({ has: page.getByText(name, { exact: true }) }).getByRole('button', { name: 'Edit agent', exact: true })
  try {
    await edit('Alice Example').click()
    await expect(dialog).toBeVisible()
    await expect.poll(() => started).toBe(true)
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(dialog).toHaveCount(0)
    await edit('Lyra Example').click()
    await expect(dialog.getByLabel('Harness', { exact: true })).toHaveValue('Current Harness')
    const lateResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/harnesses/agents/7')
    release()
    await (await lateResponse).finished()
    await dialog.getByLabel('First name *', { exact: true }).fill('Lyra edited')
    await expect(dialog.getByLabel('Harness', { exact: true })).toHaveValue('Current Harness')
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    failCatalogue = true
    await edit('Lyra Example').click()
    await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue('Lyra')
    await expect(page.getByText('Unable to load Harnesses.', { exact: true })).toBeVisible()
    // A disabled Quasar select exposes its state on the field rather than an input.
    await expect(dialog.locator('label').filter({ has: page.getByText('Harness', { exact: true }) }))
      .toHaveAttribute('aria-disabled', 'true')
    await expect(page.getByRole('option')).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    failCatalogue = false
    await edit('Lyra Example').click()
    await expect(dialog.getByLabel('Harness', { exact: true })).toHaveValue('Current Harness')
    await expect(dialog.getByLabel('Harness', { exact: true })).toBeEnabled()
  } finally { release() }
})

test('models load on demand without losing the saved profile, voice or identity draft', async ({ page }) => {
  await agentFixtures(page)
  const saved = { ...agent, agent_driver: 'internal', profile_id: 4, voice: 'realtime:12:voice%3Aecho' }
  await jsonRoute(page, '**/api/agents?*', [saved])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  await jsonRoute(page, '**/api/agents/titles?*', [{ id: 1, label: 'agent_titles.ms', gender: 'F' }])
  await jsonRoute(page, '**/api/harnesses/catalog?*', [])
  await jsonRoute(page, '**/api/harnesses/agents/7', { harness_id: null })
  await jsonRoute(page, '**/api/params', { params: [] })
  await jsonRoute(page, '**/api/llm-profiles', { profiles: [{ id: 4, label: 'Saved profile' }], current_profile_id: 4 })
  await jsonRoute(page, '**/api/llm-providers/llms', [{ id: 12, llm_provider_id: 3, service_capabilities: ['realtime_conversation'], label: 'Realtime model', provider_name: 'Synthetic provider' }])
  let release, voiceReads = 0
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/llm-providers/3/resources?*', async route => {
    voiceReads++
    await pending
    await route.fulfill({ json: { models: [{ id: 'voice:echo', name: 'Echo', resource_type: 'voice' }] } })
  })
  const writes = []
  await page.route('**/api/agents/7', route => {
    const data = route.request().postDataJSON()
    writes.push(data)
    return route.fulfill({ json: { ...saved, ...data } })
  })
  await mount(page, 'app/agent/pages/index.vue', { privileges: ['AGENT_EDIT', 'LLM_PROVIDER_ACCESS', 'PARAMS_ACCESS'] })
  try {
    await page.getByRole('button', { name: 'Edit agent', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('First name *', { exact: true }).fill('Lyra')
    expect(voiceReads).toBe(0)
    await dialog.getByRole('tab', { name: 'Models', exact: true }).click()
    await expect(dialog.getByLabel('Model profile', { exact: true })).toHaveValue('Saved profile')
    await expect.poll(() => voiceReads).toBe(1)
    await dialog.getByRole('tab', { name: 'General', exact: true }).click()
    await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue('Lyra')
    await dialog.getByRole('tab', { name: 'Models', exact: true }).click()
    expect(voiceReads).toBe(1)
    release()
    await expect(dialog.getByLabel('Voice / TTS', { exact: true })).toHaveValue('Echo')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes).toMatchObject([{ first_name: 'Lyra', profile_id: 4, voice: saved.voice }])
  } finally { release() }
})

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
