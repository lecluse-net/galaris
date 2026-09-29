import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

async function setup(page, overrides = {}) {
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
    supports_model_management: false, is_custom: false,
  }
  const other = { ...item, key: 'other', code: 'other', display_name: 'Other synthetic connection', connection: null }
  const writes = []
  const controls = { beforeSave: null, failSave: false }
  await page.route('**/api/llm-providers', route => route.fulfill({ json: [provider] }))
  await page.route('**/api/llm-providers/catalog', route => route.fulfill({
    json: { items: [{ ...item, connection: provider }, other], users: [], active_user_count: 1 },
  }))
  await page.route('**/api/llm-providers/31', route => route.fulfill({ json: provider }))
  await jsonRoute(page, '**/api/llm-providers/llms', [])
  await jsonRoute(page, '**/api/llm-providers/31/resources?*', { models: [] })
  await page.route('**/api/llm-providers/catalog/synthetic', async route => {
    const data = route.request().postDataJSON()
    writes.push(data)
    if (controls.beforeSave) await controls.beforeSave(data)
    if (controls.failSave) return route.fulfill({ status: 503, json: { detail: 'Synthetic save unavailable' } })
    provider = { ...provider, ...data, api_key_configured: Boolean(data.api_key || provider.api_key_configured) }
    delete provider.api_key
    await route.fulfill({ json: provider })
  })
  await mount(page, 'app/llm/components/ProviderWorkspace.vue', { privileges: ['LLM_PROVIDER_EDIT'] })
  const panel = page.locator('.provider-config-panel')
  await expect(panel.getByText(provider.name, { exact: true })).toBeVisible()
  await expect(panel.getByRole('textbox', { name: 'Region', exact: true })).toHaveValue(provider.configuration.region || '')
  return { panel, writes, controls, read: () => provider }
}

for (const width of [1440, 390]) {
  test(`autosave requires active complete settings and always saves deactivation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    const { panel, writes, read } = await setup(page)
    const region = panel.getByRole('textbox', { name: 'Region', exact: true })
    const token = panel.getByLabel('Token / API key', { exact: true })
    await region.fill('synthetic-region')
    expect(writes).toHaveLength(0)
    await panel.getByRole('switch').click()
    expect(writes).toHaveLength(0)
    await token.fill('synthetic-token')
    await expect.poll(() => read().is_active).toBe(true)
    await expect.poll(() => writes.length).toBe(1)
    await expect(token).toHaveValue('synthetic-token')
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
  await page.getByRole('switch').click()
  expect(await saves()).toEqual([])
  await page.getByRole('textbox', { name: 'API URL *', exact: true }).fill('https://synthetic.example.invalid')
  await expect.poll(saves).toMatchObject([{ is_active: true, api_key: null }])
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
