import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

for (const width of [1440, 390]) {
  test(`creating and reopening a multimodal LLM preserves all capabilities at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    const model = {
      id: 'synthetic-multimodal', name: 'Synthetic multimodal', resource_type: 'model',
      service_capabilities: ['vision', 'chat'], pricing: {}, context_length: 1000000,
      modalities: { input_text: true, input_image: true, input_file: true, input_audio: true, input_video: true, output_text: true },
    }
    let saved = null
    const writes = []
    await jsonRoute(page, '**/api/llm-providers', [{ id: 2, name: 'Provider', is_active: true }])
    await jsonRoute(page, '**/api/llm-providers/catalog', { items: [], users: [], active_user_count: 1 })
    await jsonRoute(page, '**/api/llm-providers/2/resources?*', { models: [model] })
    await page.route('**/api/llm-providers/llms', route => {
      if (route.request().method() === 'GET') return route.fulfill({ json: saved ? [saved] : [] })
      writes.push(route.request().postDataJSON())
      saved = { ...writes.at(-1), id: 3, provider_name: 'Provider' }
      return route.fulfill({ json: saved })
    })
    await page.route('**/api/llm-providers/llms/3', route => {
      expect(route.request().method()).toBe('PUT')
      writes.push(route.request().postDataJSON())
      saved = { ...saved, ...writes.at(-1) }
      return route.fulfill({ json: saved })
    })
    const options = { privileges: ['LLM_PROVIDER_EDIT'] }
    await mount(page, 'app/llm/components/ConfiguredLlmManager.vue', options)
    await page.getByRole('button', { name: 'Add a resource', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('combobox', { name: 'Provider', exact: true }).click()
    await page.getByRole('option', { name: 'Provider', exact: true }).click()
    await dialog.getByRole('combobox', { name: 'Model', exact: true }).fill('Synthetic')
    await page.getByRole('option', { name: /Synthetic multimodal/ }).click()
    await expect(dialog.locator('.llm-modalities')).toContainText('Chat')
    await expect(dialog.locator('.llm-modalities')).toContainText('Vision')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[0]).toMatchObject({ service_capabilities: ['chat', 'vision'], ...model.modalities })

    // Remount from the API response, then edit and save the existing model.
    await mount(page, 'app/llm/components/ConfiguredLlmManager.vue', options)
    const item = page.locator(width < 1024 ? '.llm-grid-card' : 'tbody tr').filter({ hasText: model.name })
    await expect(item).toContainText('Chat')
    await expect(item).toContainText('Vision')
    await item.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(dialog.locator('.llm-modalities')).toContainText('Chat')
    await expect(dialog.locator('.llm-modalities')).toContainText('Vision')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[1]).toMatchObject({ service_capabilities: ['chat', 'vision'], ...model.modalities })
  })
}

test('existing capabilities refresh only after preview, apply and save', async ({ page }) => {
  let saved = {
    id: 3, llm_provider_id: 2, provider_name: 'Provider', code: 'synthetic', llm_name: 'synthetic', label: 'My model',
    resource_type: 'model', primary_capability: 'chat', service_capabilities: ['chat', 'video_understanding'], pricing: {},
    input_text: true, output_text: true, input_image: false, input_file: false, input_audio: false, input_video: true,
    output_image: false, output_file: false, output_audio: false, output_video: false,
    context_length: 12000, cost_per_input_token: 0.25, is_subscription: false,
  }
  const model = {
    id: 'synthetic', name: 'Synthetic', resource_type: 'model', service_capabilities: ['chat', 'vision', 'audio_understanding'],
    modalities: { ...saved, input_image: true, input_file: true, input_audio: true, input_video: false },
    // Video is unknown: the response default must not overwrite the saved choice.
    known_modalities: ['input_text', 'output_text', 'input_image', 'input_file', 'input_audio'],
  }
  const writes = []
  let refreshes = 0
  await jsonRoute(page, '**/api/llm-providers', [{ id: 2, name: 'Provider', is_active: true }])
  await jsonRoute(page, '**/api/llm-providers/catalog', { items: [], users: [], active_user_count: 1 })
  await page.route('**/api/llm-providers/llms', route => route.fulfill({ json: [saved] }))
  await page.route('**/api/llm-providers/2/resources?*', route => {
    if (new URL(route.request().url()).searchParams.get('refresh') === 'true') refreshes++
    return route.fulfill({ json: { models: [model] } })
  })
  await page.route('**/api/llm-providers/llms/3', route => {
    writes.push(route.request().postDataJSON())
    saved = { ...saved, ...writes.at(-1) }
    return route.fulfill({ json: saved })
  })
  await mount(page, 'app/llm/components/ConfiguredLlmManager.vue', { privileges: ['LLM_PROVIDER_EDIT'] })
  const edit = page.getByRole('button', { name: 'Edit', exact: true })
  const dialog = page.getByRole('dialog')
  await edit.click()
  await expect(dialog.locator('.llm-modalities')).not.toContainText('Vision')
  expect(refreshes).toBe(0)
  await dialog.getByRole('button', { name: 'Refresh capabilities', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('No → Yes')
  expect(writes).toEqual([])
  await dialog.getByRole('status').getByRole('button', { name: 'Cancel', exact: true }).click()
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes[0]).toMatchObject({ input_image: false, input_file: false, input_audio: false, input_video: true })

  await edit.click()
  await dialog.getByRole('button', { name: 'Refresh capabilities', exact: true }).click()
  await dialog.getByRole('button', { name: 'Apply to form', exact: true }).click()
  await expect(dialog.locator('.llm-modalities')).toContainText('Vision')
  expect(writes).toHaveLength(1)
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes[1]).toMatchObject({
    input_image: true, input_file: true, input_audio: true, input_video: true,
    service_capabilities: ['chat', 'vision', 'audio_understanding', 'video_understanding'],
    label: 'My model', code: 'synthetic', cost_per_input_token: 0.25, context_length: 12000,
  })
  await edit.click()
  await expect(dialog.locator('.llm-modalities')).toContainText('Vision')
  await setPrivileges(page, [])
  await expect(dialog.getByRole('button', { name: 'Refresh capabilities', exact: true })).toHaveCount(0)
})

test('capability refresh preserves the form on errors and ignores responses from another model', async ({ page }) => {
  let release
  let pending = false
  await page.route('**/api/llm-providers/2/resources?*', async route => {
    pending = true
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { models: [{
      id: 'first', service_capabilities: ['chat', 'vision'], known_modalities: ['input_image'], modalities: { input_image: true },
    }] } })
  })
  await mount(page, 'app/llm/components/LlmCapabilityRefresh.vue', { props: {
    providerId: 2, modelName: 'first', capability: 'chat', serviceCapabilities: ['chat'],
    modalities: { input_image: false, input_text: true, output_text: true },
  } })
  await page.getByRole('button', { name: 'Refresh capabilities', exact: true }).click()
  await expect.poll(() => pending).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ modelName: 'second' }))
  const response = page.waitForResponse('**/api/llm-providers/2/resources?*')
  release()
  await response
  await expect(page.getByRole('button', { name: 'Apply to form', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => window.testApp.events)).toEqual([])

  await page.route('**/api/llm-providers/2/resources?*', route => route.fulfill({ status: 503, json: {} }))
  await page.getByRole('button', { name: 'Refresh capabilities', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Your settings are preserved')
  expect(await page.evaluate(() => window.testApp.events)).toEqual([])
})
