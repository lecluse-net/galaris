import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

async function setup(page, overrides = {}, catalogOverrides = {}) {
  let provider = {
    id: 31, name: 'Synthetic connection', provider_type: 'openai_compatible',
    base_url: 'https://provider.example.invalid', is_active: false,
    api_key_configured: false, configuration: {}, ...overrides,
  }
  const item = {
    key: 'synthetic', code: 'synthetic', display_name: provider.name,
    provider_type: provider.provider_type, auth_type: 'api_key',
    api_key_required: true, default_base_url: provider.base_url,
    icon: 'dns', color: 'primary', capabilities: ['chat'],
    configuration_fields: [{ key: 'region', label: 'Region', required: true }],
    supports_model_management: false, is_custom: false, ...catalogOverrides,
  }
  const other = { ...item, key: 'other', code: 'other', display_name: 'Other synthetic connection', connection: null }
  const writes = []
  const controls = { beforeSave: null, failSave: false }
  await page.route('**/api/llm-providers', route => route.fulfill({ json: [provider] }))
  await page.route('**/api/llm-providers/catalog', route => route.fulfill({
    json: { items: [{ ...item, connection: provider }, other], users: [], active_user_count: 1 },
  }))
  await jsonRoute(page, '**/api/llm-providers/llms', [])
  await jsonRoute(page, '**/api/llm-providers/31/resources?*', { models: [] })
  const persist = async route => {
    const data = route.request().postDataJSON()
    writes.push(data)
    if (controls.beforeSave) await controls.beforeSave(data)
    if (controls.failSave) return route.fulfill({ status: 503, json: { detail: 'Synthetic save unavailable' } })
    provider = { ...provider, ...data }
    if (Object.hasOwn(data, 'api_key')) provider.api_key_configured = Boolean(data.api_key)
    if (Object.hasOwn(data, 'management_api_key')) provider.management_api_key_configured = Boolean(data.management_api_key)
    delete provider.api_key
    delete provider.management_api_key
    await route.fulfill({ json: provider })
  }
  await page.route('**/api/llm-providers/31', route => route.request().method() === 'PUT'
    ? persist(route) : route.fulfill({ json: provider }))
  await page.route(`**/api/llm-providers/catalog/${item.code}`, persist)
  await mount(page, 'app/llm/components/ProviderWorkspace.vue', { privileges: ['LLM_PROVIDER_EDIT'] })
  const panel = page.locator('.provider-config-panel')
  await expect(panel.getByText(item.display_name, { exact: true })).toBeVisible()
  await expect(panel.getByRole('textbox', { name: 'Region', exact: true })).toHaveValue(provider.configuration.region || '')
  return { panel, writes, controls, read: () => provider }
}

for (const width of [1440, 390]) {
  test(`optional management keys save, reopen, replace and clear at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    const { panel, writes, read } = await setup(page, {
      api_key_configured: true, management_api_key_configured: false, configuration: { region: 'synthetic-region' },
    }, {
      code: 'openrouter', display_name: 'OpenRouter', supports_management_key: true,
      management_key_url: 'https://openrouter.ai/settings/management-keys',
    })
    const key = panel.getByLabel('Management key (optional)', { exact: true })
    const inferenceKey = panel.getByLabel('Token / API key', { exact: true })
    await expect(key).toHaveValue('')
    await expect(key).toHaveAttribute('type', 'password')
    await expect(inferenceKey).toHaveValue('')
    await expect(inferenceKey).toHaveAttribute('type', 'password')
    await expect(inferenceKey).toHaveAttribute('placeholder', '**********')
    await expect(panel.getByText('Token / API key', { exact: true })).toBeVisible()
    await expect(panel.getByText('Management key (optional)', { exact: true })).toBeVisible()
    await expect(panel.getByText(/Reads remaining account credits and usage/)).toBeVisible()
    await expect(panel.getByRole('link', { name: 'Create a management key on OpenRouter' }))
      .toHaveAttribute('href', 'https://openrouter.ai/settings/management-keys')
    await panel.getByRole('switch').click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0]).not.toHaveProperty('management_api_key')
    await key.fill('synthetic-management-key')
    await expect(key).toHaveAttribute('type', 'password')
    await expect.poll(() => read().management_api_key_configured).toBe(true)
    expect(writes.at(-1).management_api_key).toBe('synthetic-management-key')
    expect(writes.at(-1)).not.toHaveProperty('api_key')
    await page.locator('.provider-list-panel').getByText('Other synthetic connection', { exact: true }).click()
    await page.locator('.provider-list-panel').getByText('OpenRouter', { exact: true }).click()
    await expect(key).toHaveValue('')
    await expect(inferenceKey).toHaveValue('')
    await expect(inferenceKey).toHaveAttribute('type', 'password')
    await expect(key).toHaveAttribute('placeholder', '**********')
    await expect(panel.getByText('Management key (optional)', { exact: true })).toBeVisible()
    await expect(panel.getByText(/A management key is stored and encrypted/)).toBeVisible()
    await panel.getByRole('textbox', { name: 'Region', exact: true }).fill('changed-region')
    await expect.poll(() => read().configuration.region).toBe('changed-region')
    expect(writes.at(-1)).not.toHaveProperty('management_api_key')
    await key.fill('synthetic-replacement-key')
    await expect.poll(() => writes.at(-1).management_api_key).toBe('synthetic-replacement-key')
    await panel.getByRole('button', { name: 'Remove management key', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
    await expect.poll(() => read().management_api_key_configured).toBe(false)
    expect(writes.at(-1).management_api_key).toBeNull()
    expect(read().api_key_configured).toBe(true)
  })

  test(`autosave requires active complete settings and always saves deactivation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    const { panel, writes, read } = await setup(page)
    const region = panel.getByRole('textbox', { name: 'Region', exact: true })
    const token = panel.getByLabel('Token / API key', { exact: true })
    await expect(token).toHaveAttribute('type', 'password')
    await region.fill('synthetic-region')
    expect(writes).toHaveLength(0)
    await panel.getByRole('switch').click()
    expect(writes).toHaveLength(0)
    await token.fill('synthetic-token')
    await expect.poll(() => read().is_active).toBe(true)
    await expect.poll(() => writes.length).toBe(1)
    await expect(token).toHaveValue('synthetic-token')
    await expect(token).toHaveAttribute('type', 'password')
    await region.fill('')
    await panel.getByRole('switch').click()
    await expect.poll(() => read().is_active).toBe(false)
    expect(writes.at(-1).configuration.region).toBe('')
    await page.locator('.provider-list-panel').getByText('Other synthetic connection', { exact: true }).click()
    await page.locator('.provider-list-panel').getByText('Synthetic connection', { exact: true }).click()
    await expect(panel.getByRole('switch')).not.toBeChecked()
    await expect(token).toHaveValue('')
    await expect(region).toHaveValue('')
  })
}

for (const custom of [false, true]) {
  test(`stored API keys can be removed and replaced without revealing them (custom: ${custom})`, async ({ page }) => {
    const { panel, writes, controls, read } = await setup(page, {
      is_active: true, api_key_configured: true, configuration: { region: 'initial-region' },
    }, custom ? { key: 'custom:31', code: null, is_custom: true,
      auth_type: 'optional_api_key', api_key_required: false } : {})
    const key = panel.getByLabel('Token / API key', { exact: true })
    const remove = panel.getByRole('button', { name: 'Remove API key', exact: true })
    await expect(key).toHaveValue('')
    await expect(key).toHaveAttribute('placeholder', '**********')
    await expect(panel.getByText('Token / API key', { exact: true })).toBeVisible()
    await remove.click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(writes).toHaveLength(0)
    controls.failSave = true
    await remove.click()
    await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(page.getByText('Synthetic save unavailable', { exact: true })).toBeVisible()
    expect(read().api_key_configured).toBe(true)
    expect(writes.at(-1)).toMatchObject({ api_key: null, is_active: custom })
    controls.failSave = false
    await panel.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => read().api_key_configured).toBe(false)
    expect(read().is_active).toBe(custom)
    await expect(remove).toHaveCount(0)
    await expect(key).toHaveValue('')
    await key.fill('synthetic-new-key')
    if (!custom) await panel.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => read().api_key_configured).toBe(true)
    await expect(key).toHaveAttribute('type', 'password')
    await page.locator('.provider-list-panel').getByText('Other synthetic connection', { exact: true }).click()
    await page.locator('.provider-list-panel').getByText('Synthetic connection', { exact: true }).click()
    await expect(key).toHaveValue('')
    await expect(key).toHaveAttribute('placeholder', '**********')
    expect(writes.at(-1).api_key).toBe('synthetic-new-key')
  })
}

test('successful tests save inactive drafts; failed and obsolete tests do not', async ({ page }) => {
  const { panel, writes } = await setup(page)
  let success = false
  let releaseTest
  let holdTest = false
  await page.route('**/api/llm-providers/test', async route => {
    if (holdTest) await new Promise(resolve => { releaseTest = resolve })
    await route.fulfill({ json: {
      success, models_count: 2, provider_name: 'Synthetic connection', message: 'Synthetic test result',
    } })
  })
  await panel.getByRole('textbox', { name: 'Region', exact: true }).fill('tested-region')
  await panel.getByLabel('Token / API key', { exact: true }).fill('synthetic-token')
  const testButton = panel.getByRole('button', { name: 'Test connection', exact: true })
  await testButton.click()
  await expect(panel.getByText('Synthetic test result')).toBeVisible()
  expect(writes).toHaveLength(0)
  success = true
  await testButton.click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ is_active: false, api_key: 'synthetic-token', configuration: { region: 'tested-region' } })
  await expect(panel.getByText(/2 models available/)).toBeVisible()
  holdTest = true
  await testButton.click()
  await expect.poll(() => Boolean(releaseTest)).toBe(true)
  await panel.getByRole('textbox', { name: 'Region', exact: true }).fill('newer-region')
  const response = page.waitForResponse('**/api/llm-providers/test')
  releaseTest()
  await response
  await expect(testButton).toBeEnabled()
  expect(writes).toHaveLength(1)
  await expect(panel.getByRole('textbox', { name: 'Region', exact: true })).toHaveValue('newer-region')
})

for (const navigate of [false, true]) {
test(`pending saves preserve newer edits (navigate: ${navigate})`, async ({ page }) => {
  const { panel, writes, controls, read } = await setup(page, {
    is_active: true, api_key_configured: true, configuration: { region: 'initial-region' },
  })
  let releaseSave
  controls.beforeSave = () => new Promise(resolve => { releaseSave = resolve })
  const region = panel.getByRole('textbox', { name: 'Region', exact: true })
  await region.fill('first-region')
  await expect.poll(() => Boolean(releaseSave)).toBe(true)
  await region.fill('latest-region')
  if (navigate) await page.locator('.provider-list-panel').getByText('Other synthetic connection', { exact: true }).click()
  controls.beforeSave = null
  releaseSave()
  await expect.poll(() => read().configuration.region).toBe('latest-region')
  expect(writes.map(value => value.configuration.region)).toEqual(['first-region', 'latest-region'])
  expect(writes.every(value => !('api_key' in value))).toBe(true)
  if (navigate) {
    await expect(panel.getByText('Other synthetic connection', { exact: true })).toBeVisible()
    await expect(region).toHaveValue('')
    await page.locator('.provider-list-panel').getByText('Synthetic connection', { exact: true }).click()
  }
  await expect(region).toHaveValue('latest-region')
})
}

test('custom providers with optional keys wait for their name and URL', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 1100 })
  await mount(page, 'app/llm/components/ProviderConfigPanel.vue', {
    privileges: ['LLM_PROVIDER_EDIT'], props: {
      item: {
        key: 'custom:32', code: null, display_name: 'Synthetic custom connection',
        provider_type: 'openai_compatible', auth_type: 'optional_api_key', api_key_required: false,
        is_custom: true, default_base_url: '', configuration_fields: [], connection: null,
      },
      detail: null, users: [], activeUserCount: 1,
    },
  })
  const saves = () => page.evaluate(() => window.testApp.events.filter(event => event.name === 'auto-save').map(event => event.value))
  await expect(page.getByLabel('Token / API key', { exact: true })).toHaveAttribute('type', 'password')
  await page.getByRole('switch').click()
  expect(await saves()).toEqual([])
  await page.getByRole('textbox', { name: 'API URL *', exact: true }).fill('https://synthetic.example.invalid')
  await expect.poll(saves).toMatchObject([{ is_active: true }])
  expect((await saves())[0].api_key).toBeUndefined()
  await page.getByRole('textbox', { name: /Provider name/ }).fill('')
  expect(await saves()).toHaveLength(1)
  await page.getByRole('switch').focus()
  await page.keyboard.press('Space')
  await expect.poll(saves).toMatchObject([{ is_active: true }, { is_active: false, name: '' }])
})

test('rapid deactivation and reactivation keep the latest toggle while earlier saves complete', async ({ page }) => {
  const { panel, controls, read } = await setup(page, {
    is_active: true, api_key_configured: true, configuration: { region: 'initial-region' },
  })
  const releases = []
  controls.beforeSave = () => new Promise(resolve => { releases.push(resolve) })
  const toggle = panel.getByRole('switch')
  await toggle.click()
  await expect.poll(() => releases.length).toBe(1)
  await toggle.click()
  releases[0]()
  await expect.poll(() => releases.length).toBe(2)
  await expect(toggle).toBeChecked()
  releases[1]()
  await expect.poll(() => read().is_active).toBe(true)
  await expect(toggle).toBeChecked()
})

test('an incomplete subscription can be disabled without acknowledging or selecting an owner', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 1100 })
  await mount(page, 'app/llm/components/ProviderConfigPanel.vue', {
    privileges: ['LLM_PROVIDER_EDIT'], props: {
      item: {
        key: 'openai-codex', code: 'openai-codex', display_name: 'Synthetic subscription',
        provider_type: 'openai_compatible', auth_type: 'oauth_device', is_custom: false,
        default_base_url: 'https://synthetic.example.invalid', configuration_fields: [],
        connection: { is_active: true, user_id: null, subscription_acknowledged: false, oauth_connected: false },
      },
      detail: null, users: [], activeUserCount: 1,
    },
  })
  await page.getByRole('switch').click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'auto-save').map(event => event.value)))
    .toMatchObject([{ is_active: false, user_id: null, subscription_acknowledged: false }])
})

test('save errors preserve input for retry and missing edit privileges prevent autosave', async ({ page }) => {
  const { panel, writes, controls, read } = await setup(page, {
    is_active: true, api_key_configured: true, configuration: { region: 'initial-region' },
  })
  controls.failSave = true
  const region = panel.getByRole('textbox', { name: 'Region', exact: true })
  await region.fill('retry-region')
  await expect(page.getByText('Synthetic save unavailable', { exact: true })).toBeVisible()
  await expect(region).toHaveValue('retry-region')
  controls.failSave = false
  await panel.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => read().configuration.region).toBe('retry-region')
  await setPrivileges(page, [])
  await region.fill('forbidden-region')
  await expect(panel.getByRole('switch')).toBeDisabled()
  expect(writes).toHaveLength(2)
})
