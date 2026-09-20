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
    await page.route('**/api/llm-profiles', route => route.fulfill({ json: { profiles: [profile], current_profile_id: 1 } }))
    await page.route('**/api/llm-profiles/1', route => {
      expect(route.request().method()).toBe('PUT')
      const update = route.request().postDataJSON()
      updates.push(update)
      profile = { ...profile, ...update }
      return route.fulfill({ json: profile })
    })
    const options = { locale: 'fr', privileges: ['PARAMS_EDIT'] }
    await mount(page, 'app/llm/components/LlmUsageManager.vue', options)
    const row = page.getByRole('row').filter({ has: page.getByText('Texte standard', { exact: true }) })
    const select = row.getByRole('combobox')
    const effort = row.getByRole('slider')
    await expect(row).toContainText('Briefing, exécuteur standard, suivi des objectifs et modèles équivalents à Claude Opus ou GPT Terra.')
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
    await effort.locator('[tabindex="0"]').focus()
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
    await effort.locator('[tabindex="0"]').focus()
    await page.keyboard.press('PageDown')
    await expect.poll(() => updates.at(-1)).toEqual({ text_standard_reasoning_effort: null })
    await expect(effort).toHaveAttribute('aria-valuetext', 'Auto')
    await setPrivileges(page, [])
    await expect(row.locator('.usage-select')).toHaveAttribute('aria-disabled', 'true')
    await expect(effort).toHaveAttribute('aria-disabled', 'true')
    expect(updates).toHaveLength(4)
  })
}
