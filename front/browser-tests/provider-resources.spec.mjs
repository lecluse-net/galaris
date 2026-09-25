import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const provider = {
  id: 21, name: 'Synthetic provider', provider_type: 'openai_compatible',
  base_url: 'https://provider.example.invalid', is_active: true, configuration: {},
}
const catalogItem = {
  key: 'synthetic', code: 'synthetic', display_name: provider.name,
  provider_type: provider.provider_type, auth_type: 'api_key', default_base_url: provider.base_url,
  icon: 'dns', color: 'primary', capabilities: ['chat', 'vision', 'speech'],
  configuration_fields: [], supports_model_management: false, is_custom: false, connection: provider,
}
const documentModel = {
  id: 'document-reader', name: 'Synthetic document reader', resource_type: 'model',
  service_capabilities: ['chat', 'vision'],
  modalities: { input_file: true, input_image: true, output_text: true },
}
const models = [
  documentModel,
  { id: 'vision-only', name: 'Synthetic vision only', resource_type: 'model', service_capabilities: ['chat', 'vision'], modalities: { input_image: true, output_text: true } },
  { id: 'unknown', name: 'Synthetic unknown inputs', resource_type: 'model', service_capabilities: ['chat'], modalities: null },
  { id: 'file-output', name: 'Synthetic file output', resource_type: 'model', service_capabilities: ['chat'], modalities: { output_file: true, output_text: true } },
  { id: 'no-text', name: 'Synthetic nontext output', resource_type: 'model', service_capabilities: ['chat'], modalities: { input_file: true, output_text: false } },
]

async function setup(page, items = [catalogItem]) {
  await jsonRoute(page, '**/api/llm-providers', items.map(item => item.connection))
  await jsonRoute(page, '**/api/llm-providers/catalog', { items, users: [], active_user_count: 1 })
  await jsonRoute(page, '**/api/llm-providers/21', provider)
  await jsonRoute(page, '**/api/llm-providers/llms', [])
}

async function selectCategory(page, label) {
  await page.getByRole('combobox', { name: 'Resource type', exact: true }).click()
  await page.getByRole('option', { name: label, exact: true }).click()
}

for (const width of [1440, 390]) {
  test(`document catalog selects native readers and preserves model metadata at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1100 })
    await setup(page)
    await jsonRoute(page, '**/api/llm-providers/21/resources?*', { models })
    await mount(page, 'app/llm/components/ProviderWorkspace.vue', { privileges: ['LLM_PROVIDER_EDIT'], containerStyle: { height: '100vh' } })
    const panel = page.locator('.provider-models-panel')
    await expect(panel.getByText(documentModel.name, { exact: true })).toBeVisible()
    await selectCategory(page, 'Documents / PDF')
    await expect(panel.locator('.model-name')).toHaveText([documentModel.name])
    await expect(panel).toContainText('1 resource(s) published by Synthetic provider')
    await expect(panel).toContainText('Incomplete metadata')

    await page.getByRole('combobox', { name: 'Resource type', exact: true }).click()
    await expect(page.getByRole('option', { name: 'Documents / PDF', exact: true })).toBeVisible()
    await expect(page.locator('.q-menu')).toHaveCSS('opacity', '1')
    await page.screenshot({ path: testInfo.outputPath('resource-menu-light.png') })
    await page.keyboard.press('Escape')
    await page.evaluate(() => window.testApp.dark(true))
    await page.getByRole('combobox', { name: 'Resource type', exact: true }).click()
    await expect(page.getByRole('option', { name: 'Documents / PDF', exact: true })).toBeVisible()
    await expect(page.locator('.q-menu')).toHaveCSS('opacity', '1')
    await page.screenshot({ path: testInfo.outputPath('resource-menu-dark.png') })
    await page.keyboard.press('Escape')

    const search = panel.getByPlaceholder('Search resources…')
    await search.fill('absent')
    await expect(panel.getByText('No model found', { exact: true })).toBeVisible()
    await search.fill('')
    await panel.locator('.model-item').getByRole('button').click()
    await expect.poll(() => page.evaluate(() => window.testApp.events.at(-1)?.value)).toEqual({ providerId: 21, model: documentModel })

    await selectCategory(page, 'Chat')
    await expect(panel.getByText('Synthetic vision only', { exact: true })).toBeVisible()
    await selectCategory(page, 'Documents / PDF')
    await expect(panel.locator('.model-name')).toHaveText([documentModel.name])
    await setPrivileges(page, [])
    await expect(panel.locator('.model-item').getByRole('button')).toHaveCount(0)
  })
}

test('resource changes ignore late results, recover from errors and adapt to another provider', async ({ page }) => {
  const speechProvider = { ...catalogItem, key: 'speech', code: 'speech', display_name: 'Synthetic speech provider', capabilities: ['speech'], connection: null, auth_type: 'optional_api_key' }
  await setup(page, [catalogItem, speechProvider])
  const voice = { id: 'voice', name: 'Synthetic voice', resource_type: 'voice', service_capabilities: ['speech'] }
  await jsonRoute(page, '**/api/llm-providers/catalog/speech/resources?*', { models: [voice] })
  let releaseVision
  let failChat = false
  await page.route('**/api/llm-providers/21/resources?*', async route => {
    const capability = new URL(route.request().url()).searchParams.get('capability')
    if (capability === 'vision') {
      await new Promise(resolve => { releaseVision = resolve })
      return route.fulfill({ json: { models: [models[1]] } })
    }
    return failChat
      ? route.fulfill({ status: 503, json: { detail: 'Synthetic catalog unavailable' } })
      : route.fulfill({ json: { models } })
  })
  await mount(page, 'app/llm/components/ProviderWorkspace.vue', { privileges: ['LLM_PROVIDER_EDIT'], containerStyle: { height: '100vh' } })
  const panel = page.locator('.provider-models-panel')
  await expect(panel.getByText(documentModel.name, { exact: true })).toBeVisible()
  await selectCategory(page, 'Vision')
  await expect.poll(() => Boolean(releaseVision)).toBe(true)
  await selectCategory(page, 'Documents / PDF')
  await expect(panel.locator('.model-name')).toHaveText([documentModel.name])
  const response = page.waitForResponse(url => url.url().includes('capability=vision'))
  releaseVision()
  await response
  await expect(panel.locator('.model-name')).toHaveText([documentModel.name])

  failChat = true
  await panel.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(panel).toContainText('Synthetic catalog unavailable')
  failChat = false
  await panel.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(panel.locator('.model-name')).toHaveText([documentModel.name])

  await page.locator('.provider-list-panel').getByText(speechProvider.display_name, { exact: true }).click()
  await expect(panel.getByText(voice.name, { exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: 'Resource type', exact: true }).click()
  await expect(page.getByRole('option', { name: 'TTS', exact: true })).toBeVisible()
  await expect(page.getByRole('option', { name: 'Documents / PDF', exact: true })).toHaveCount(0)
})
