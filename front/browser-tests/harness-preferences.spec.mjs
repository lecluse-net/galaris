import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

function entry(id, name, containerized = true, enabled = false) {
  return { id, name, provider_code: containerized ? id : 'openai_messages', provider_label: name, driver_code: id, containerized, enabled,
    base_url: containerized ? null : 'https://external.example.test/v1', model: containerized ? null : 'external-model',
    settings: {}, token_configured: !containerized, assigned_agents: enabled ? 2 : 0, revision: 1, capabilities: [], last_error: null }
}

async function fixtures(page) {
  await jsonRoute(page, '**/api/harness-manager/release', { version: '1.1.0', update_url: 'https://galaris.test/api/harness-manager/updates', sha256: 'test', size: 100 })
  const entries = [entry('hermes', 'Hermes'), entry('codex', 'Codex', true, true),
    entry('claude_agent', 'Claude Agent'), entry('deepseek_harness', 'DeepSeek'), entry('external', 'Independent API', false, true)]
  const writes = []
  const state = { failLoad: false, failSave: false }
  await page.route('**/api/harnesses/catalog?*', route => route.fulfill(state.failLoad
    ? { status: 503, json: { detail: 'Unavailable' } } : { json: entries }))
  await page.route('**/api/harnesses/catalog/*', route => {
    const item = entries.find(item => item.id === route.request().url().split('/').at(-1))
    if (route.request().method() === 'GET') return route.fulfill({ json: item })
    const body = route.request().postDataJSON()
    writes.push(body)
    if (state.failSave) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
    Object.assign(item, body)
    if (!item.enabled) item.assigned_agents = 0
    return route.fulfill({ json: item })
  })
  await jsonRoute(page, '**/api/params', { params: [
    { name: 'hermes.default.config', value: 'max_turns: 42', configured: true, secret: false },
    { name: 'hermes.default.data-env', value: 'EXAMPLE=value', configured: true, secret: false },
    { name: 'harness.default.compose', value: 'services: {}', configured: true, secret: false },
  ] })
  await jsonRoute(page, '**/api/harnesses/execution-configurations', [])
  await jsonRoute(page, '**/api/harness-manager/configuration', {
    manager_url: 'https://manager.example.test', galaris_api_url: '', secret_configured: true,
  })
  await jsonRoute(page, '**/api/harness-manager/diagnostics', {
    state: 'ok', manager_url: 'https://manager.example.test', secret_configured: true,
    galaris_api_url: 'https://galaris.example.test/api', public_api_url: 'https://galaris.example.test/api',
    api_url_source: 'APP_HOST', api_issue: 'none', runtime_api_check: 'not_checked', legacy_environment_detected: false,
  })
  return { entries, writes, state }
}

const open = (page, options = {}) => mount(page, 'core/params/components/PreferencesSectionPage.vue', {
  props: { section: 'harnesses' }, route: '/params/harnesses?tab=managed', privileges: ['PARAMS_ACCESS', 'PARAMS_EDIT'], ...options,
})
const openTasks = page => open(page, { props: { section: 'tasks' }, route: '/params/tasks' })

function pipelineConfigurations(internalPlanner, externalPlanner, briefingEfforts = [], externalBriefing = false) {
  return ['internal', 'future-runtime'].map(provider_code => ({
    provider_code, label: provider_code === 'internal' ? 'agent.harnessInternal' : 'Future runtime', revision: 0,
    pipeline_policy: {
      use_planner: provider_code === 'internal' ? internalPlanner : externalPlanner,
      use_briefing: provider_code !== 'internal' && externalBriefing,
      briefing_efforts: provider_code === 'internal' ? [] : briefingEfforts,
    },
    descriptor: { configurable: [], policy: {
      disabled_capabilities: [], max_parallel_tasks: null, execution_timeout_seconds: null,
      idle_timeout_seconds: null, stream_close_timeout_seconds: 5,
      max_message_bytes: 1000000, max_result_bytes: 16000000, max_stream_bytes: 64000000,
    } },
  }))
}

for (const [scenario, internalPlanner, externalPlanner, externalBriefing, efforts] of [
  ['current harnesses', true, false, false, []],
  ['no eligible harness', false, false, false, []],
  ['shared planning and external briefing', true, true, true, ['standard']],
  ['briefing without an eligible effort', false, false, true, []],
]) {
  test(`pipeline settings list only eligible harnesses: ${scenario}`, async ({ page }) => {
    await fixtures(page)
    await jsonRoute(page, '**/api/harnesses/execution-configurations', pipelineConfigurations(internalPlanner, externalPlanner, efforts, externalBriefing))
    await openTasks(page)
    await expect(page.getByRole('region', { name: 'Per-run limits', exact: true })).toBeVisible()
    const planner = page.getByRole('region', { name: 'Planner', exact: true })
    const briefing = page.getByRole('region', { name: 'Briefing', exact: true })
    await expect(planner).toHaveCount(Number(internalPlanner || externalPlanner))
    if (internalPlanner || externalPlanner) {
      await expect(planner.getByRole('listitem')).toHaveText([
        ...(internalPlanner ? ['Internal harness (Galaris)'] : []), ...(externalPlanner ? ['Future runtime'] : []),
      ])
    }
    await expect(briefing).toHaveCount(Number(externalBriefing && efforts.length > 0))
    if (externalBriefing && efforts.length) await expect(briefing.getByRole('listitem')).toHaveText(['Future runtime'])
    await setPrivileges(page, ['PARAMS_ACCESS'])
    if (internalPlanner || externalPlanner) await expect(planner.locator('textarea')).toHaveAttribute('readonly', '')
    if (externalBriefing && efforts.length) await expect(briefing.locator('textarea')).toHaveAttribute('readonly', '')
  })
}

test('pipeline prompts recover loading and saving errors, preserve drafts and persist on reopen', async ({ page }, testInfo) => {
  await fixtures(page)
  let failLoad = true
  let failSave = true
  await page.route('**/api/harnesses/execution-configurations', route => route.fulfill(failLoad
    ? { status: 503, json: { detail: 'Unavailable' } }
    : { json: pipelineConfigurations(true, false, ['standard'], true) }))
  const params = ['planner', 'briefing'].map(key => ({
    name: `ai.${key}-system-prompt`, value: `Existing ${key}`, configured: true, secret: false,
    prompt: { default_value: `Default ${key}`, customized: true, default_changed: false },
  }))
  await page.route('**/api/params', route => route.fulfill({ json: { params } }))
  await page.route('**/api/params/ai.*-system-prompt', route => {
    if (failSave) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
    const param = params.find(item => route.request().url().endsWith(item.name))
    param.value = route.request().postDataJSON().value
    return route.fulfill({ json: { ...param, status: 'success' } })
  })
  const reopen = () => openTasks(page)
  await reopen()
  await expect(page.getByRole('alert').filter({ hasText: 'Unable to load settings' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Planner', exact: true })).toHaveCount(0)
  failLoad = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  for (const key of ['planner', 'briefing']) {
    const region = page.getByRole('region', { name: key === 'planner' ? 'Planner' : 'Briefing', exact: true })
    await expect(region.locator('textarea')).toHaveValue(`Existing ${key}`)
    await region.locator('textarea').fill(`Saved ${key}`)
  }
  await page.getByRole('button', { name: /Task creation/ }).click()
  await page.getByRole('button', { name: /Task creation/ }).click()
  const planner = page.getByRole('region', { name: 'Planner', exact: true })
  const briefing = page.getByRole('region', { name: 'Briefing', exact: true })
  await expect(planner.locator('textarea')).toHaveValue('Saved planner')
  await planner.getByRole('button', { name: 'Save customization', exact: true }).click()
  await expect(page.getByText('Could not save the setting')).toBeVisible()
  // The shared prompt editor restores the persisted value after a rejected save.
  await expect(planner.locator('textarea')).toHaveValue('Existing planner')
  failSave = false
  await planner.locator('textarea').fill('Saved planner')
  for (const region of [planner, briefing]) await region.getByRole('button', { name: 'Save customization', exact: true }).click()
  await expect.poll(() => params.map(item => item.value)).toEqual(['Saved planner', 'Saved briefing'])
  await reopen()
  await expect(planner.locator('textarea')).toHaveValue('Saved planner')
  await expect(briefing.locator('textarea')).toHaveValue('Saved briefing')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('pipeline-mobile.png'), fullPage: true })
})

test('managed toggles persist, reveal Hermes configuration and confirm agent reassignment', async ({ page }, testInfo) => {
  const { entries, writes, state } = await fixtures(page)
  entries[0].assigned_agents = 3
  await open(page)
  const hermes = page.getByRole('switch', { name: 'Enable Hermes', exact: true })
  const config = page.getByRole('region', { name: 'Hermes configuration', exact: true })
  await expect(hermes).not.toBeChecked()
  await expect(config).toHaveCount(0)
  await hermes.click()
  await expect(hermes).toBeChecked()
  await expect(config.locator('textarea').first()).toHaveValue('max_turns: 42')
  await expect(config.getByText('To configure an agent, open its page and select the Hermes tab.')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('hermes-defaults-mobile.png'), fullPage: true })
  expect(writes[0]).toMatchObject({ enabled: true, settings: {}, model: null, base_url: null })
  expect(writes[0]).not.toHaveProperty('token')
  await hermes.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('3')
  await expect(dialog).toContainText('internal')
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(dialog).toHaveCount(0)
  await expect(hermes).toBeChecked()
  expect(writes).toHaveLength(1)
  await hermes.click()
  await dialog.getByRole('button', { name: 'Disable', exact: true }).click()
  await expect(hermes).not.toBeChecked()
  await expect(config).toHaveCount(0)
  await hermes.click()
  await expect(config.locator('textarea').first()).toHaveValue('max_turns: 42')
  state.failSave = true
  const claude = page.getByRole('switch', { name: 'Enable Claude Agent', exact: true })
  await claude.click()
  await expect(page.getByRole('alert').filter({ hasText: /Unable to change Harness activation/ })).toBeVisible()
  await expect(claude).not.toBeChecked()
  await setPrivileges(page, ['PARAMS_ACCESS'])
  await expect(hermes).toBeDisabled()
  await expect(claude).toBeDisabled()
})

test('tabs separate managed and external harnesses and preserve manager drafts', async ({ page }, testInfo) => {
  await fixtures(page)
  await jsonRoute(page, '**/api/browser/status', { enabled: false })
  await open(page, { locale: 'fr' })
  const navigation = await page.evaluate(async () => {
    const { useNavigation } = await import('/core/navigation/index.ts')
    const node = useNavigation().findByPath('admin.params.harnesses')
    return { to: node?.to, children: Object.keys(node?.children ?? {}) }
  })
  expect(navigation).toEqual({ to: '/params/harnesses', children: [] })
  const url = page.getByRole('textbox', { name: 'URL du manager', exact: true })
  await expect(url).toBeVisible()
  await url.fill('https://draft.example.test')
  await page.getByRole('tab', { name: 'Harnais externes', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.query.tab)).toBe('external')
  await expect(page.getByText('Independent API', { exact: true })).toBeVisible()
  await expect(page.getByRole('switch')).toHaveCount(0)
  await expect(url).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Modifier', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Ajouter une API OpenAI Messages', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('external-desktop.png'), fullPage: true })
  await page.getByRole('tab', { name: 'Harnais managés', exact: true }).click()
  await expect(url).toHaveValue('https://draft.example.test')
  await expect(page.getByText('Independent API', { exact: true })).not.toBeVisible()
  await page.mouse.move(0, 0)
  await page.screenshot({ path: testInfo.outputPath('managed-desktop.png'), fullPage: true })
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    await page.evaluate(() => window.testApp.dark(true))
    await expect(page.getByRole('tab', { name: 'Harnais managés', exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Harnais externes', exact: true })).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`managed-mobile-dark-${width}.png`), fullPage: true })
  }
  await open(page, { route: '/params/harnesses?tab=external', privileges: ['PARAMS_ACCESS'] })
  await expect(page.getByText('Independent API', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'View', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add an OpenAI Messages API', exact: true })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Common settings', exact: true })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Internal harness', exact: true })).toHaveCount(0)
})

test('catalogue failures remain explicit and can be retried', async ({ page }) => {
  const { state } = await fixtures(page)
  state.failLoad = true
  await open(page)
  await expect(page.getByRole('alert')).toContainText('Unable to load')
  state.failLoad = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('switch', { name: 'Enable Hermes', exact: true })).toBeVisible()
})

test('external harnesses are created, reopened, updated and deleted from a modal', async ({ page }, testInfo) => {
  const { entries, writes, state } = await fixtures(page)
  await page.route('**/api/harnesses/catalog', route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    const created = { ...entry('created', body.name, false), ...body, token_configured: true }
    delete created.token
    entries.push(created)
    return route.fulfill({ json: created })
  })
  await jsonRoute(page, '**/api/harnesses/catalog/probe', { base_url: 'https://new.example.test/v1', models: ['new-model'] })
  await open(page, { route: '/params/harnesses?tab=external' })
  await page.getByRole('button', { name: 'Add an OpenAI Messages API', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Harness name', { exact: true }).fill('New API')
  await dialog.getByLabel('API base URL', { exact: true }).fill('https://new.example.test/v1')
  await dialog.getByLabel('API key', { exact: true }).fill('test-private-key')
  await dialog.getByRole('button', { name: 'Test connection', exact: true }).click()
  await expect(dialog.getByText('new-model', { exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('external-modal-mobile.png'), fullPage: true })
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  const row = page.getByRole('listitem').filter({ hasText: 'New API' })
  await expect(row).toBeVisible()
  expect(writes[0]).toMatchObject({ name: 'New API', token: 'test-private-key', model: 'new-model' })
  await row.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog.getByLabel('Harness name', { exact: true })).toHaveValue('New API')
  await expect(dialog.getByLabel('API key', { exact: true })).toHaveValue('')
  await dialog.getByLabel('Harness name', { exact: true }).fill('Renamed API')
  state.failSave = true
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(2)
  await expect(page.getByRole('alert').filter({ hasText: 'Unavailable' })).toBeVisible()
  await expect(dialog.getByLabel('Harness name', { exact: true })).toHaveValue('Renamed API')
  state.failSave = false
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('listitem').filter({ hasText: 'Renamed API' })).toBeVisible()
  expect(writes.at(-1)).not.toHaveProperty('token')
  await page.getByRole('listitem').filter({ hasText: 'Renamed API' }).getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog.getByLabel('Harness name', { exact: true })).toHaveValue('Renamed API')
  await dialog.getByLabel('Harness name', { exact: true }).fill('Discard me')
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
  await expect(dialog).toHaveCount(0)
  await page.getByRole('listitem').filter({ hasText: 'Renamed API' }).getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog.getByLabel('Harness name', { exact: true })).toHaveValue('Renamed API')
  await dialog.getByRole('button', { name: 'Delete', exact: true }).click()
  const confirmation = page.getByRole('dialog').filter({ hasText: 'Permanently delete' })
  await expect(confirmation).toContainText('internal Galaris Harness')
  await page.route('**/api/harnesses/catalog/created', route => route.fulfill({ status: 204 }))
  await confirmation.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('listitem').filter({ hasText: 'Renamed API' })).toHaveCount(0)
  await setPrivileges(page, ['PARAMS_ACCESS'])
  await page.getByRole('button', { name: 'View', exact: true }).click()
  await expect(dialog.getByLabel('Harness name', { exact: true })).toHaveAttribute('readonly')
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0)
})

test('closing a modal ignores late loads and saves update the list without closing a new form', async ({ page }) => {
  const { entries } = await fixtures(page)
  let releaseLoad
  const pendingLoad = new Promise(resolve => { releaseLoad = resolve })
  await page.route('**/api/harnesses/catalog/external', async route => {
    await pendingLoad
    await route.fulfill({ json: entries.at(-1) })
  })
  await open(page, { route: '/params/harnesses?tab=external' })
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: 'Add an OpenAI Messages API', exact: true }).click()
  releaseLoad()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Harness name', { exact: true })).toHaveValue('OpenAI Messages API')
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.unroute('**/api/harnesses/catalog/external')
  let releaseSave
  const pendingSave = new Promise(resolve => { releaseSave = resolve })
  await page.route('**/api/harnesses/catalog/external', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: entries.at(-1) })
    await pendingSave
    await route.fulfill({ json: { ...entries.at(-1), name: 'Saved after closing' } })
  })
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await dialog.getByLabel('Harness name', { exact: true }).fill('Saved after closing')
  const request = page.waitForRequest(request => request.method() === 'PUT')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await request
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: 'Add an OpenAI Messages API', exact: true }).click()
  releaseSave()
  await expect(page.getByRole('listitem').filter({ hasText: 'Saved after closing' })).toBeAttached()
  await expect(dialog.getByLabel('Harness name', { exact: true })).toHaveValue('OpenAI Messages API')
})

test('each harness configuration saves its own provider policy and preserves internal drafts', async ({ page }, testInfo) => {
  const { state } = await fixtures(page)
  state.failLoad = true
  const configurations = ['openai_messages', 'codex', 'internal'].map(provider_code => ({
    provider_code, label: provider_code, revision: 1, descriptor: {
      configurable: [], policy: { disabled_capabilities: [], max_parallel_tasks: provider_code === 'internal' ? 2 : 6,
        execution_timeout_seconds: null, idle_timeout_seconds: null, stream_close_timeout_seconds: 5,
        max_message_bytes: 1000000, max_result_bytes: 16000000, max_stream_bytes: 64000000 },
    },
  }))
  await page.route('**/api/harnesses/execution-configurations', route => {
    return route.fulfill({ json: configurations })
  })
  const writes = []
  await page.route('**/api/harnesses/execution-configurations/*', route => {
    const provider = route.request().url().split('/').at(-1)
    const body = route.request().postDataJSON()
    writes.push({ provider, ...body })
    const current = configurations.find(item => item.provider_code === provider)
    current.revision++
    current.descriptor.policy = body.policy
    return route.fulfill({ json: current })
  })
  await open(page, { route: '/params/harnesses' })
  const internalPanel = page.getByRole('tabpanel', { name: 'Internal harness', exact: true })
  const concurrency = internalPanel.getByLabel('Maximum concurrent tasks', { exact: true })
  await expect(concurrency).toHaveValue('2')
  await expect(page.getByLabel('Harness', { exact: true })).toHaveCount(0)
  await concurrency.fill('3')
  await page.getByRole('tab', { name: 'Managed harnesses', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Unable to load')
  state.failLoad = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  const managedPolicy = page.getByRole('region', { name: 'Codex configuration', exact: true })
  await expect(managedPolicy.getByLabel('Maximum concurrent tasks', { exact: true })).toHaveValue('6')
  await managedPolicy.getByLabel('Maximum concurrent tasks', { exact: true }).fill('7')
  await page.getByRole('tab', { name: 'Internal harness', exact: true }).click()
  await expect(concurrency).toHaveValue('3')
  await internalPanel.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(internalPanel.getByRole('status')).toHaveText('Settings saved.')
  expect(writes[0]).toMatchObject({ provider: 'internal', expected_revision: 1, policy: { max_parallel_tasks: 3 } })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.testApp.dark(true))
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('internal-mobile-dark.png'), fullPage: true })
  await page.getByRole('tab', { name: 'Managed harnesses', exact: true }).click()
  await expect(managedPolicy.getByLabel('Maximum concurrent tasks', { exact: true })).toHaveValue('7')
  await managedPolicy.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(managedPolicy.getByRole('status')).toHaveText('Settings saved.')
  expect(writes[1]).toMatchObject({ provider: 'codex', expected_revision: 1, policy: { max_parallel_tasks: 7 } })
  await page.getByRole('tab', { name: 'External harnesses', exact: true }).click()
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  const externalPolicy = page.getByRole('dialog').getByRole('region', { name: 'Harness reliability and capabilities', exact: true })
  await expect(externalPolicy).toContainText('This policy applies to all harnesses using the openai_messages provider.')
  await externalPolicy.getByLabel('Maximum concurrent tasks', { exact: true }).fill('8')
  await externalPolicy.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(externalPolicy.getByRole('status')).toHaveText('Settings saved.')
  expect(writes[2]).toMatchObject({ provider: 'openai_messages', expected_revision: 1, policy: { max_parallel_tasks: 8 } })
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(externalPolicy.getByLabel('Maximum concurrent tasks', { exact: true })).toHaveValue('8')
  // Reopening must preserve the saved policy, independently of framework load counts.
  await open(page, { route: '/params/harnesses?tab=internal' })
  await expect(concurrency).toHaveValue('3')
  await setPrivileges(page, ['PARAMS_ACCESS'])
  await expect(concurrency).not.toBeVisible()
})

for (const tab of ['common', 'advanced']) {
  test(`legacy ${tab} links lead to task execution preferences`, async ({ page }) => {
    await fixtures(page)
    await open(page, { route: `/params/harnesses?tab=${tab}` })
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/params/tasks')
  })
}
