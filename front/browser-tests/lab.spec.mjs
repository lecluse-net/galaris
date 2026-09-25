import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const parameterSchema = {
  type: 'object',
  properties: {
    label: { type: 'string', default: '' },
    language: { type: 'string', default: 'en' },
    agent: { type: 'object', default: {} },
    effort: { anyOf: [{ $ref: '#/$defs/Effort' }, { type: 'null' }], default: null },
    can_clarify: { type: 'boolean', default: true },
    max_nodes: { type: 'integer', minimum: 1, maximum: 500, default: 24 },
    system_prompt: { type: 'string', default: 'Prepare a clear and verified report.' },
    history: { type: 'array', default: [] },
    resources: { type: 'array', default: [] },
    agent_configuration: { $ref: '#/$defs/AgentConfiguration' },
    protocol: { const: 'fixed' },
  },
  $defs: {
    Effort: { type: 'string', enum: ['standard', 'high'] },
    AgentConfiguration: { type: 'object', properties: { name: { type: 'string' } } },
  },
}

test('parameter sections keep edits and invalid drafts while searching and collapsing', async ({ page }) => {
  await mount(page, 'app/lab/components/LabParameterEditor.vue', { props: {
    schema: parameterSchema, modelValue: { label: 'Research', agent: { name: 'Ada' }, language: 'fr' },
  } })
  await expect(page.locator('[data-parameter="protocol"]')).toHaveCount(0)
  await expect(page.getByLabel('Label', { exact: true })).toHaveValue('Research')
  await expect(page.getByLabel('Language', { exact: true })).toHaveValue('fr')
  const agent = page.locator('[data-parameter="agent"]')
  await expect(agent).toContainText('Ada')
  await agent.locator('.q-item').first().click()
  await agent.locator('textarea').fill('{invalid')
  const invalid = () => page.evaluate(() => window.testApp.events.filter(event => event.name === 'invalid').at(-1)?.value)
  await expect.poll(invalid).toBe(true)
  await page.getByRole('button', { name: 'Collapse all', exact: true }).click()
  await expect(page.locator('.parameter-section').first()).toContainText('1 value to correct')
  await page.getByLabel('Find a parameter', { exact: true }).fill('max_nodes')
  await expect(page.locator('.parameter-field:visible')).toHaveCount(1)
  await page.getByLabel('Maximum nodes', { exact: true }).fill('12')
  await expect.poll(invalid).toBe(true)
  await page.getByLabel('Find a parameter', { exact: true }).fill('unknown field')
  await expect(page.getByRole('status')).toHaveText('No parameters match this search.')
  await page.getByLabel('Find a parameter', { exact: true }).fill('agent')
  await expect(agent.locator('textarea')).toHaveValue('{invalid')
  await agent.locator('textarea').fill('{"name":"Grace"}')
  await expect.poll(invalid).toBe(false)
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toEqual({ label: 'Research', agent: { name: 'Grace' }, language: 'fr', max_nodes: 12 })
})

test('parameter forms resolve nullable enums and preserve read-only values', async ({ page }) => {
  await mount(page, 'app/lab/components/LabParameterEditor.vue', { props: { schema: parameterSchema, modelValue: { effort: null } } })
  await page.getByRole('button', { name: 'Expand all', exact: true }).click()
  await page.getByLabel('Effort', { exact: true }).click()
  await page.getByRole('option', { name: 'high', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toEqual({ effort: 'high' })
  await page.locator('[data-parameter="effort"] .q-field__focusable-action').click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)).toEqual({ effort: null })
  await page.evaluate(() => window.testApp.setProps({ readonly: true }))
  await expect(page.getByLabel('Language', { exact: true })).not.toBeEditable()
  await expect(page.getByLabel('Maximum nodes', { exact: true })).not.toBeEditable()
  await expect(page.getByRole('switch')).toHaveAttribute('aria-disabled', 'true')
})

test('dataset settings save their revision and preserve other parameters on desktop and mobile', async ({ page }) => {
  let releaseInitialLoad
  const initialLoad = new Promise(resolve => { releaseInitialLoad = resolve })
  const dataset = {
    id: 'dataset', name: 'Préparer un rapport', revision: 1, description: 'Comparer la préparation de rapports à partir du même contexte.',
    parameters: { label: 'Recherche documentaire', language: 'fr', agent: { name: 'Ada', role: 'Analyste' }, resources: ['memory://reports/quarterly'], max_nodes: 24 },
    configuration: { system_prompt: 'Prépare un rapport clair, concis et vérifiable.' }, prompt_suffix: null,
  }
  await jsonRoute(page, '**/api/evaluation/mechanisms', [{
    key: 'briefing', executor: null, configuration_schema: { properties: { system_prompt: { type: 'string' } } }, algorithm: {},
    contract: { variable_name: 'objective', variable_schema: { type: 'string' }, parameters_schema: parameterSchema, parameter_defaults: {}, result_name: 'briefing_and_resources' },
  }])
  await jsonRoute(page, '**/api/evaluation/config', { lab_llm_id: null, llms: [] })
  await page.route('**/api/evaluation/briefing/datasets', async route => {
    await initialLoad
    await route.fulfill({ json: [dataset] })
  })
  await jsonRoute(page, '**/api/evaluation/briefing/datasets/dataset/cases', [])
  await jsonRoute(page, '**/api/evaluation/briefing/datasets/dataset/runs?*', [])
  const saved = []
  await page.route('**/api/evaluation/briefing/datasets/dataset', async route => {
    expect(route.request().method()).toBe('PATCH')
    saved.push(route.request().postDataJSON())
    await route.fulfill({ json: { ...dataset, ...saved.at(-1), revision: saved.length + 1 } })
  })
  await mount(page, 'app/lab/components/LabWorkbench.vue', { props: { mechanism: 'briefing', canEdit: true }, locale: 'fr' })
  const newDataset = page.getByRole('button', { name: 'Nouveau jeu', exact: true })
  await expect(newDataset).toBeDisabled()
  releaseInitialLoad()
  await newDataset.click()
  const creation = page.getByRole('dialog')
  await expect(creation.getByLabel('Nom', { exact: true })).toBeEditable()
  await creation.getByRole('button', { name: 'Annuler', exact: true }).click()
  await expect(creation).not.toBeVisible()
  await page.getByRole('tab', { name: 'Paramètres du jeu', exact: true }).click()
  await expect(page.getByText('Paramètres enregistrés', { exact: true })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Paramètres du jeu', exact: true })).toHaveAttribute('aria-selected', 'true')
  await page.screenshot({ path: '/artifacts/lab-parameters-desktop.png', animations: 'disabled' })
  await page.getByLabel('Rechercher un paramètre', { exact: true }).fill('nœuds')
  await page.getByLabel('Nombre maximal de nœuds', { exact: true }).fill('12')
  await expect(page.getByText('Modifications non enregistrées', { exact: true })).toBeVisible()
  const save = page.getByRole('button', { name: 'Enregistrer', exact: true })
  await save.click()
  await expect.poll(() => saved).toEqual([{
    revision: 1, name: dataset.name, description: dataset.description,
    parameters: { ...dataset.parameters, max_nodes: 12 }, configuration: dataset.configuration, prompt_suffix: null,
  }])
  await page.getByLabel('Rechercher un paramètre', { exact: true }).fill('')
  await page.setViewportSize({ width: 390, height: 900 })
  await page.evaluate(() => window.testApp.dark(true))
  await page.getByLabel('Libellé', { exact: true }).fill('Rapport mobile')
  await save.click()
  await expect.poll(() => saved).toHaveLength(2)
  expect(saved[1]).toMatchObject({ revision: 2, parameters: { ...dataset.parameters, label: 'Rapport mobile', max_nodes: 12 } })
  await expect(page.getByText('Paramètres enregistrés', { exact: true })).toBeVisible()
})

test('Lab input actions show dismissible error toasts without changing the modal', async ({ page }) => {
  const dataset = { id: 'dataset', name: 'Test dataset', revision: 1, description: '', parameters: {}, configuration: {}, prompt_suffix: null }
  const input = { variable_value: 'Prepare a report' }
  await jsonRoute(page, '**/api/evaluation/mechanisms', [{
    key: 'briefing', executor: null, configuration_schema: {}, algorithm: {},
    contract: { variable_name: 'objective', variable_schema: { type: 'string' }, parameters_schema: {}, parameter_defaults: {}, result_name: 'briefing_and_resources' },
  }])
  await jsonRoute(page, '**/api/evaluation/config', { lab_llm_id: null, llms: [] })
  await jsonRoute(page, '**/api/evaluation/briefing/datasets', [dataset])
  await jsonRoute(page, '**/api/evaluation/briefing/datasets/dataset/cases', [{
    id: 'item', name: 'Report', revision: 1, enabled: true, readiness: 'draft',
    input_data: input, expected_output: {}, source_capture: {},
  }])
  await jsonRoute(page, '**/api/evaluation/briefing/datasets/dataset/runs?*', [])
  await mount(page, 'app/lab/components/LabWorkbench.vue', { props: { mechanism: 'briefing', canEdit: true } })
  await page.getByRole('tab', { name: 'Items', exact: true }).click()
  await page.getByRole('button', { name: 'View', exact: true }).click()
  const dialog = page.getByRole('dialog')
  for (const [label, path, body, location, result] of [
    ['Preview inputs', 'datasets/dataset/preview', input, ['body', 'variable_value'], { input, candidate_prompt: 'Report preview' }],
    ['Suggest a reference for review', 'cases/item/generate-expected', { input_data: input }, ['body', 'input_data', 'variable_value'], { output: { result: 'Reference report' } }],
  ]) {
    let valid = false
    await page.route(`**/api/evaluation/briefing/${path}`, async route => {
      expect(route.request().postDataJSON()).toEqual(body)
      await route.fulfill(valid
        ? { json: result }
        : { status: 422, json: { detail: [{ loc: location, msg: 'Field required', type: 'missing' }] } })
    })
    await dialog.getByRole('button', { name: label, exact: true }).click()
    const toast = page.locator('.q-notification[role="alert"]')
    await expect(toast).toContainText(`${location.join('.')}: Field required`)
    // The API diagnostic now complements the field-level validation message.
    await expect(toast).toContainText('HTTP 422')
    await expect(dialog.locator('.text-negative')).toHaveCount(0)
    await toast.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(toast).toHaveCount(0)
    await expect(dialog).toBeVisible()
    await expect(dialog.getByLabel('Variable: Objective', { exact: true })).toHaveValue(input.variable_value)
    await dialog.getByRole('button', { name: label, exact: true }).click()
    await expect(toast).toBeVisible()
    valid = true
    await dialog.getByRole('button', { name: label, exact: true }).click()
    await expect(toast).toHaveCount(0)
  }
  await expect(dialog.locator('textarea').nth(1)).toHaveValue(/Reference report/)
})

test('each item edits and sends its own history for previews, references and saving', async ({ page }) => {
  const dataset = { id: 'dataset', name: 'History dataset', revision: 1, parameters: { language: 'en' }, configuration: {} }
  const original = '<p>Continue &amp; verify</p><p>2 &lt; 3</p>'
  const items = ['First', 'Second'].map((name, index) => ({
    id: `item-${index}`, name, revision: 1, enabled: true, readiness: 'draft',
    input_data: { variable_value: original, context: { history: [{ text: `${name} conversation` }] } },
    expected_output: {}, source_capture: {},
  }))
  await jsonRoute(page, '**/api/evaluation/mechanisms', [{
    key: 'briefing', executor: null, configuration_schema: {}, algorithm: {},
    contract: {
      variable_name: 'objective', variable_schema: { type: 'string' },
      parameters_schema: { properties: { language: { type: 'string' } } }, parameter_defaults: { language: 'en' },
      context_schema: { properties: { history: { type: 'array' } } }, context_defaults: { history: [] },
      result_name: 'briefing_and_resources',
    },
  }])
  await jsonRoute(page, '**/api/evaluation/config', { lab_llm_id: null, llms: [] })
  await jsonRoute(page, '**/api/evaluation/briefing/datasets', [dataset])
  await jsonRoute(page, '**/api/evaluation/briefing/datasets/dataset/cases', items)
  await jsonRoute(page, '**/api/evaluation/briefing/datasets/dataset/runs?*', [])
  const sent = []
  for (const [path, result] of [
    ['datasets/dataset/preview', { candidate_prompt: 'Preview' }],
    ['cases/item-0/generate-expected', { output: { result: 'Reference' } }],
    ['cases/item-0', { ...items[0], revision: 2 }],
  ]) {
    await page.route(`**/api/evaluation/briefing/${path}`, async route => {
      sent.push(route.request().postDataJSON())
      await route.fulfill({ json: result })
    })
  }
  await mount(page, 'app/lab/components/LabWorkbench.vue', { props: { mechanism: 'briefing', canEdit: true } })
  await page.getByRole('tab', { name: 'Dataset settings', exact: true }).click()
  await expect(page.locator('[data-parameter="history"]')).toHaveCount(0)
  await page.getByRole('tab', { name: 'Items', exact: true }).click()
  await expect(page.locator('.value-preview').first()).toHaveText('Continue & verify 2 < 3')
  await page.getByRole('button', { name: 'View', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  const history = dialog.locator('[data-parameter="history"]')
  await expect(dialog.locator('[data-parameter="language"]')).toHaveCount(0)
  await history.locator('.q-item').first().click()
  await expect(history.locator('textarea')).toHaveValue(/First conversation/)
  await history.locator('textarea').fill('{invalid')
  for (const name of ['Preview inputs', 'Suggest a reference for review', 'Save']) {
    await expect(dialog.getByRole('button', { name, exact: true })).toBeDisabled()
  }
  const context = { history: [{ text: 'Edited first conversation', attachments: ['tool://files/report'] }] }
  await history.locator('textarea').fill(JSON.stringify(context.history))
  const input = { variable_value: original, context }
  await dialog.getByRole('button', { name: 'Preview inputs', exact: true }).click()
  await expect.poll(() => sent[0]).toEqual(input)
  await dialog.getByRole('button', { name: 'Suggest a reference for review', exact: true }).click()
  await expect.poll(() => sent[1]).toEqual({ input_data: input })
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => sent[2]?.input_data).toEqual(input)
  await expect(dialog).not.toBeVisible()
  await page.getByRole('button', { name: 'View', exact: true }).nth(1).click()
  await history.locator('.q-item').first().click()
  await expect(history.locator('textarea')).toHaveValue(/Second conversation/)
  await expect(history.locator('textarea')).not.toHaveValue(/Edited first/)
})
