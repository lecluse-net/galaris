import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const modelFields = [
  'text_ultra_low', 'text_low', 'text_standard', 'text_high', 'vision', 'document',
  'audio', 'video', 'sound_generation', 'music_generation', 'video_generation',
  'image', 'transcription', 'vector',
]

for (const width of [1440, 390]) {
  test(`model assignments and effort remain editable and persist at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1100 })
    let profile = {
      id: 1, label: 'Profil principal', created_at: '2026-09-11T10:00:00Z', updated_at: null,
      ...Object.fromEntries(modelFields.map(name => [name + '_llm_id', null])),
      ...Object.fromEntries(['text_ultra_low', 'text_low', 'text_standard', 'text_high'].map(name => [name + '_reasoning_effort', null])),
      text_standard_llm_id: 2,
    }
    const updates = []
    await jsonRoute(page, '**/api/llm-providers/llms', [
      { id: 2, label: 'Modèle standard', provider_name: 'Fournisseur A', primary_capability: 'chat', service_capabilities: ['chat'], output_text: true },
      { id: 7, label: 'Modèle alternatif', provider_name: 'Fournisseur B', primary_capability: 'vision', service_capabilities: ['vision', 'chat'], input_text: true, input_image: true, output_text: true },
    ])
    await page.route('**/api/llm-profiles', route => route.fulfill({
      json: { profiles: [profile], current_profile_id: 1, default_fallback_profile_id: null },
    }))
    await page.route('**/api/llm-profiles/1', route => {
      expect(route.request().method()).toBe('PUT')
      const update = route.request().postDataJSON()
      updates.push(update)
      profile = { ...profile, ...update }
      return route.fulfill({ json: profile })
    })
    const options = { locale: 'fr', privileges: ['LLM_PROFILE_EDIT'] }
    await mount(page, 'app/llm/components/LlmUsageManager.vue', options)
    const row = page.getByRole('row').filter({ has: page.getByText('Texte standard', { exact: true }) })
    const select = row.getByRole('combobox')
    const effort = row.getByRole('slider')
    await expect(row).toContainText('Modèle standard (Fournisseur A)')
    await expect(effort).toHaveAttribute('aria-valuetext', 'Auto')
    await page.screenshot({ path: testInfo.outputPath('light.png'), fullPage: true, animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath('dark.png'), fullPage: true, animations: 'disabled' })
    if (width === 1440) {
      await page.setViewportSize({ width: 1024, height: 1100 })
      await page.screenshot({ path: testInfo.outputPath('desktop-1024.png'), fullPage: true, animations: 'disabled' })
      await page.setViewportSize({ width, height: 1100 })
    }

    await select.click()
    await page.getByRole('option', { name: 'Modèle alternatif (Fournisseur B)', exact: true }).click()
    await expect.poll(() => updates.at(-1)).toEqual({ text_standard_llm_id: 7 })
    await expect(effort).not.toHaveAttribute('aria-disabled', 'true')
    await effort.focus()
    await page.keyboard.press('PageUp')
    await expect.poll(() => updates.at(-1)).toEqual({ text_standard_reasoning_effort: 'max' })
    await expect(effort).toHaveAttribute('aria-valuetext', 'Maximum')

    const visionRow = page.getByRole('row').filter({ has: page.getByText('Modèle d’analyse d’image', { exact: true }) })
    await visionRow.getByRole('combobox').click()
    await page.getByRole('option', { name: 'Modèle alternatif (Fournisseur B)', exact: true }).click()
    await expect.poll(() => updates.at(-1)).toEqual({ vision_llm_id: 7 })

    await mount(page, 'app/llm/components/LlmUsageManager.vue', options)
    await expect(row).toContainText('Modèle alternatif (Fournisseur B)')
    await expect(visionRow).toContainText('Modèle alternatif (Fournisseur B)')
    await expect(effort).toHaveAttribute('aria-valuetext', 'Maximum')
    await effort.focus()
    await page.keyboard.press('PageDown')
    await expect.poll(() => updates.at(-1)).toEqual({ text_standard_reasoning_effort: null })
    await expect(effort).toHaveAttribute('aria-valuetext', 'Auto')
    await setPrivileges(page, [])
    await expect(row.locator('.usage-select')).toHaveAttribute('aria-disabled', 'true')
    await expect(effort).toHaveAttribute('aria-disabled', 'true')
    expect(updates).toHaveLength(4)
  })
}

test('browsing models and changing either default are independent', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 950 })
  const profiles = [
    { id: 1, label: 'Default', code: 'primary', text_standard_llm_id: 11 },
    { id: 2, label: 'API fallback', code: 'api-fallback', text_standard_llm_id: 22 },
    { id: 3, label: 'Other', code: 'other', text_standard_llm_id: 33 },
    { id: 4, label: 'New primary', code: 'new-primary', text_standard_llm_id: 44 },
  ]
  let current = 1
  let selected = null
  let failNext = true
  await jsonRoute(page, '**/api/llm-providers/llms', [
    { id: 11, label: 'Default model' },
    { id: 22, label: 'Fallback model' },
    { id: 33, label: 'Other model' },
    { id: 44, label: 'New primary model' },
  ].map(model => ({ ...model, provider_name: 'Synthetic API', primary_capability: 'chat', service_capabilities: ['chat'] })))
  await page.route('**/api/llm-profiles', route => route.fulfill({
    json: { profiles, current_profile_id: current, default_fallback_profile_id: selected },
  }))
  await page.route('**/api/llm-profiles/*/use', route => {
    expect(route.request().method()).toBe('POST')
    current = Number(new URL(route.request().url()).pathname.split('/').at(-2))
    return route.fulfill({ json: { profile_id: current, current_profile_id: current } })
  })
  await page.route('**/api/llm-profiles/default-fallback', route => {
    expect(route.request().method()).toBe('PUT')
    if (failNext) {
      failNext = false
      return route.fulfill({ status: 503, json: {} })
    }
    selected = route.request().postDataJSON().default_fallback_profile_id
    return route.fulfill({ json: { default_fallback_profile_id: selected } })
  })
  const options = { route: '/llm?tab=usage', shell: true, privileges: ['LLM_PROFILE_EDIT'] }
  const open = () => mount(page, 'app/llm/pages/index.vue', options)
  await open()

  const primary = page.getByRole('combobox', { name: 'Primary profile', exact: true })
  const fallback = page.getByRole('combobox', { name: 'Default fallback profile', exact: true })
  const displayed = page.getByRole('combobox', { name: 'Displayed profile', exact: true })
  const standardRow = page.getByRole('row').filter({ has: page.getByText('Standard text', { exact: true }) })
  const pick = async (field, label) => {
    await field.click()
    await expect(field).toHaveAttribute('aria-controls', /.+/)
    const popupId = await field.getAttribute('aria-controls')
    await page.locator(`[id="${popupId}"]`).getByRole('option', { name: label, exact: true }).click()
  }
  await pick(fallback, 'API fallback')
  await expect(page.getByText('Could not save the default fallback profile', { exact: true })).toBeVisible()
  expect(selected).toBeNull()
  await pick(fallback, 'API fallback')
  await expect.poll(() => selected).toBe(2)
  await expect(standardRow).toContainText('Default model')
  expect(current).toBe(1)
  await pick(displayed, 'Other')
  await expect(standardRow).toContainText('Other model')
  expect(current).toBe(1)
  expect(selected).toBe(2)
  await pick(primary, 'New primary')
  await expect.poll(() => current).toBe(4)
  expect(selected).toBe(2)
  await expect(standardRow).toContainText('Other model')
  await page.screenshot({ path: testInfo.outputPath('independent-profiles-desktop.png'), animations: 'disabled' })

  await open()
  await expect(standardRow).toContainText('New primary model')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.testApp.dark(true))
  await fallback.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('fallback-mobile-dark.png'), animations: 'disabled' })
  await page.locator('label').filter({ has: fallback }).getByRole('button', { name: 'Clear', exact: true }).click()
  await expect.poll(() => selected).toBeNull()
  await expect(standardRow).toContainText('New primary model')
  expect(current).toBe(4)
  await setPrivileges(page, ['LLM_PROFILE_ACCESS'])
  await expect(primary).toHaveAttribute('readonly', '')
  await expect(fallback).toHaveAttribute('readonly', '')
  await pick(displayed, 'Default')
  await expect(standardRow).toContainText('Default model')
  expect(current).toBe(4)
})
