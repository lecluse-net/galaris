import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const width of [1440, 390]) {
  test(`creating and reopening a multimodal LLM preserves all capabilities at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    const model = {
      id: 'deepseek/deepseek-v4.1-flash', name: 'DeepSeek V4.1 Flash', resource_type: 'model',
      service_capabilities: ['vision', 'chat'], pricing: {}, context_length: 1000000,
      modalities: { input_text: true, input_image: true, output_text: true },
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
    await dialog.getByRole('combobox', { name: 'Model', exact: true }).fill('DeepSeek')
    await page.getByRole('option', { name: /DeepSeek V4.1 Flash/ }).click()
    await expect(dialog.locator('.llm-modalities')).toContainText('Chat')
    await expect(dialog.locator('.llm-modalities')).toContainText('Vision')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[0]).toMatchObject({ service_capabilities: ['chat', 'vision'], input_text: true, input_image: true, output_text: true })

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
    expect(writes[1]).toMatchObject({ service_capabilities: ['chat', 'vision'], input_text: true, input_image: true, output_text: true })
  })
}
